#!/usr/bin/env python3

# Documentation
# https://docs.nvidia.com/grid/10.0/grid-vgpu-user-guide/index.html#vgpu-information-in-sysfs-file-system
# https://man7.org/linux/man-pages/man5/sysfs.5.html

import sys
import argparse
import logging
import os
import os.path
import time
from collections import OrderedDict
from typing import Sequence

LOG = logging.getLogger(__name__)

MDEV_BUS_CLASS_PATH = "/sys/class/mdev_bus"

MDEV_BUS_DEVICE_PATH = "/sys/bus/mdev/devices"

PCI_BUS_DEVICE_PATH = "/sys/bus/pci/devices"

NVIDIA_VENDOR = "10de"


class DevCtlException(Exception):
    pass


class InvalidPCIDeviceName(DevCtlException):
    def __init__(self, name):
        super().__init__("No such PCI device: '{}'".format(name))
        self.name = name


class InvalidDeviceDriverPath(DevCtlException):
    def __init__(self, path):
        super().__init__("No such device driver path: '{}'".format(path))
        self.path = path


class NoMdevBusPath(DevCtlException):
    def __init__(self, path):
        super().__init__("No such MDEV path: '{}'".format(path))
        self.path = path


class InvalidMdevPCIAddress(DevCtlException):
    def __init__(self, pci_address):
        super().__init__("No such MDEV PCI address: '{}'".format(pci_address))
        self.pci_address = pci_address


class InvalidMdevUUID(DevCtlException):
    def __init__(self, uuid):
        super().__init__("No such MDEV UUID: '{}'".format(uuid))
        self.uuid = uuid


class InvalidMdevFileFormat(DevCtlException):
    pass


# https://stackoverflow.com/questions/9535954/printing-lists-as-tabular-data
def print_table(table):
    longest_cols = [(max([len(str(row[i])) for row in table]) + 3) for i in range(len(table[0]))]
    row_format = "".join(["{:<" + str(longest_col) + "}" for longest_col in longest_cols])
    for row in table:
        print(row_format.format(*row))


def each_mdev_device_class_pci_address():
    for pci_address in sorted(os.listdir(MDEV_BUS_CLASS_PATH)):
        yield pci_address


def each_supported_mdev_type_and_path(pci_address):
    path = os.path.join(MDEV_BUS_CLASS_PATH, pci_address, "mdev_supported_types")
    for mdev_type in sorted(os.listdir(path)):
        yield mdev_type, os.path.join(path, mdev_type)


def each_mdev_device_uuid():
    for uuid in sorted(os.listdir(MDEV_BUS_DEVICE_PATH)):
        yield uuid


def each_pci_device_and_path(vendor=None):
    if vendor and not vendor.startswith("0x"):
        vendor = "0x" + vendor

    for dev in sorted(os.listdir(PCI_BUS_DEVICE_PATH)):
        dev_path = os.path.join(PCI_BUS_DEVICE_PATH, dev)
        vendor_path = os.path.join(dev_path, "vendor")
        if vendor and os.path.exists(vendor_path):
            with open(vendor_path) as f:
                device_vendor = f.read().rstrip("\n")
            if device_vendor != vendor:
                continue
        yield dev, dev_path


def get_driver_of_device(dev):
    if not dev:
        raise InvalidPCIDeviceName(dev)
    driver_path = "/sys/bus/pci/devices/{}/driver".format(dev)
    if not os.path.exists(driver_path):
        raise InvalidDeviceDriverPath(driver_path)
    driver_path = os.path.realpath(driver_path)
    driver_name = os.path.basename(driver_path)
    return driver_name


class MdevType:
    def __init__(self, path):
        self.path = path
        self.realpath = os.path.realpath(path)
        self.type = os.path.basename(self.realpath)
        self.update()

    def create(self, uuid):
        with open(os.path.join(self.path, "create"), "w") as f:
            print(uuid, file=f)
        self.update()

    def update(self):
        fields = (("name", str), ("description", str), ("device_api", str), ("available_instances", int))
        for field_name, field_type in fields:
            with open(os.path.join(self.path, field_name)) as f:
                setattr(self, field_name, field_type(f.read().rstrip("\n")))

    def __repr__(self):
        return "MdevType(path={!r})".format(self.path)

    def __str__(self):
        return "<MdevType path={!r} realpath={!r} type={!r} name={!r} description={!r} device_api={!r} available_instances={!r}>".format(
            self.path, self.realpath, self.type, self.name, self.description, self.device_api, self.available_instances,
        )

    @classmethod
    def from_path(cls, path):
        return cls(path)


class MdevDeviceClass:
    def __init__(self, pci_address, path):
        self.pci_address = pci_address  # PCI address
        self.path = path  # device path
        self._supported_mdev_types = None  # maps mdev_type to MdevType

    @property
    def supported_mdev_types(self) -> Sequence[MdevType]:
        if self._supported_mdev_types is None:
            self._supported_mdev_types = OrderedDict()
            for mdev_type, mdev_type_path in each_supported_mdev_type_and_path(self.pci_address):
                self._supported_mdev_types[mdev_type] = MdevType.from_path(mdev_type_path)
        return self._supported_mdev_types

    def __repr__(self):
        return "MdevDeviceClass(pci_address={!r}, path={!r})".format(self.pci_address, self.path)

    def __str__(self):
        return "<MdevDeviceClass pci_address={!r} path={!r} supported_mdev_types={!r}>".format(
            self.pci_address, self.path, list(self.supported_mdev_types.keys())
        )

    @classmethod
    def from_pci_address(cls, pci_address):
        if not os.path.exists(MDEV_BUS_CLASS_PATH):
            raise NoMdevBusPath(MDEV_BUS_CLASS_PATH)
        path = os.path.join(MDEV_BUS_CLASS_PATH, pci_address)
        if not os.path.exists(path):
            raise InvalidMdevPCIAddress(pci_address)

        return cls(pci_address=pci_address, path=path)

    @classmethod
    def from_pci_address_unchecked(cls, pci_address):
        path = os.path.join(MDEV_BUS_CLASS_PATH, pci_address)
        return cls(pci_address=pci_address, path=path)


class MdevNvidia:
    def __init__(self, path, vm_name, vgpu_params):
        self.path = path
        self.vm_name = vm_name
        self.vgpu_params = vgpu_params

    def __str__(self):
        return "mdev_nvidia path={} vm_name={} vgpu_params={}".format(self.vm_name, self.vgpu_params)

    def __repr__(self):
        return "MdevNvidia(path={!r}, vm_name={!r}, vgpu_params={!r})".format(self.path, self.vm_name, self.vgpu_params)

    @classmethod
    def from_path(cls, path):
        fields = ("vm_name", "vgpu_params")
        kwargs = {"path": path}
        for field in fields:
            with open(os.path.join(path, field)) as f:
                kwargs[field] = f.read().rstrip("\n")
        return cls(**kwargs)


class MdevDevice:
    def __init__(self, uuid, path):
        self.uuid = uuid  # mdev device UUID
        self.path = path  # device path
        self.realpath = os.path.realpath(path)
        self.pci_address = os.path.basename(os.path.dirname(self.realpath))
        self._mdev_type = None
        self._nvidia = None

    @property
    def mdev_type(self) -> MdevType:
        if self._mdev_type is None:
            self._mdev_type = MdevType.from_path(os.path.join(self.path, "mdev_type"))
        return self._mdev_type

    @property
    def nvidia(self) -> MdevNvidia:
        if self._nvidia is None:
            nvidia_path = os.path.join(self.path, "nvidia")
            if os.path.exists(nvidia_path):
                self._nvidia = MdevNvidia.from_path(nvidia_path)
        return self._nvidia

    @classmethod
    def from_uuid(cls, uuid):
        if not os.path.exists(MDEV_BUS_DEVICE_PATH):
            raise NoMdevBusPath(MDEV_BUS_DEVICE_PATH)
        path = os.path.join(MDEV_BUS_DEVICE_PATH, uuid)
        if not os.path.exists(path):
            raise InvalidMdevUUID(uuid)

        return cls(uuid=uuid, path=path)

    @classmethod
    def from_uuid_unchecked(cls, uuid):
        path = os.path.join(MDEV_BUS_DEVICE_PATH, uuid)
        return cls(uuid=uuid, path=path)


class Waiter:
    def __init__(self, check_func, message, num_trials=3, wait_delay=1):
        self.check_func = check_func
        self.message = message
        self.num_trials = num_trials
        self.wait_delay = wait_delay

    def wait(self):
        trial = 0
        result = False
        while not result:
            result = self.check_func()
            if result:
                break
            if self.num_trials > 0:
                trial += 1
                if trial > self.num_trials:
                    break
                LOG.info("[Trial %d / %d] %s", trial, self.num_trials, self.message)
            else:
                LOG.info("[Trying] %s", self.message)
            time.sleep(self.wait_delay)
        return result


class DevCtl:
    def __init__(self, wait_for_device=False, num_trials=3, wait_delay=1):
        if wait_for_device:
            self.waiter = Waiter(
                check_func=self._check_device,
                message="Wait for paths {} and {}".format(MDEV_BUS_CLASS_PATH, MDEV_BUS_DEVICE_PATH),
                num_trials=num_trials,
                wait_delay=wait_delay,
            )
        else:
            self.waiter = None
        self.wait_for_device()
        self._mdev_device_classes = None  # maps PCI address to MdevDeviceClass
        self._mdev_devices = None  # maps UUID to MdevDevice

    def _check_device(self):
        return os.path.exists(MDEV_BUS_CLASS_PATH) and os.path.exists(MDEV_BUS_DEVICE_PATH)

    @property
    def wait_for_device_enabled(self):
        return self.waiter is not None

    def wait_for_device(self):
        if self.waiter is not None:
            self.waiter.wait()
        if not os.path.exists(MDEV_BUS_CLASS_PATH):
            raise NoMdevBusPath(MDEV_BUS_CLASS_PATH)
        if not os.path.exists(MDEV_BUS_DEVICE_PATH):
            raise NoMdevBusPath(MDEV_BUS_DEVICE_PATH)

    @property
    def mdev_device_classes(self):
        if self._mdev_device_classes is None:
            self._mdev_device_classes = OrderedDict()
            for pci_address in each_mdev_device_class_pci_address():
                self._mdev_device_classes[pci_address] = MdevDeviceClass.from_pci_address_unchecked(pci_address)
        return self._mdev_device_classes

    @property
    def mdev_devices(self):
        if self._mdev_devices is None:
            self._mdev_devices = OrderedDict()
            for uuid in each_mdev_device_uuid():
                self._mdev_devices[uuid] = MdevDevice.from_uuid_unchecked(uuid)
        return self._mdev_devices

    def print_mdev_device_classes(self, pci_addresses_filter, mdev_types_filter):
        mdev_types = [
            ("PCI ADDRESS", "MDEV TYPE", "NAME", "AVAILABLE INSTANCES", "DESCRIPTION", "MDEV DEVICE CLASS PATH")
        ]
        for mdev_device_class in self.mdev_device_classes.values():
            if pci_addresses_filter and mdev_device_class.pci_address not in pci_addresses_filter:
                continue

            for mdev_type in mdev_device_class.supported_mdev_types.values():
                if not mdev_types_filter or mdev_type.type in mdev_types_filter:
                    mdev_types.append(
                        (
                            mdev_device_class.pci_address,
                            mdev_type.type,
                            mdev_type.name,
                            mdev_type.available_instances,
                            mdev_type.description,
                            mdev_device_class.path,
                        )
                    )

        print_table(mdev_types)

    def print_mdev_devices(self, pci_addresses_filter, mdev_types_filter):
        mdev_devices = [
            ("MDEV DEVICE UUID", "PCI ADDRESS", "TYPE", "NAME", "AVAILABLE INSTANCES", "DESCRIPTION", "VM NAME")
        ]
        for mdev_device in self.mdev_devices.values():
            if not mdev_types_filter or mdev_device.mdev_type.type in mdev_types_filter:
                mdev_devices.append(
                    (
                        mdev_device.uuid,
                        mdev_device.pci_address,
                        mdev_device.mdev_type.type,
                        mdev_device.mdev_type.name,
                        mdev_device.mdev_type.available_instances,
                        mdev_device.mdev_type.description,
                        mdev_device.nvidia.vm_name if mdev_device.nvidia else "none",
                    )
                )

        print_table(mdev_devices)

    def print_pci_devices(self, pci_addresses_filter):
        pci_devices = [("PCI ADDRESS", "DEVICE DRIVER", "PCI DEVICE PATH")]
        for m in each_pci_device_and_path(vendor=NVIDIA_VENDOR):
            device_name, device_path = m
            try:
                driver_name = get_driver_of_device(device_name)
            except InvalidPCIDeviceName:
                driver_name = "no driver"
            except InvalidDeviceDriverPath:
                driver_name = "no driver path"
            pci_devices.append((device_name, driver_name, device_path))

        print_table(pci_devices)

    def save_mdev(self, output_file):
        output_file.write("# MDEV UUID Reservation\n")
        output_file.write("# This file is auto-generated by nvidia-dev-ctl.py\n")
        for mdev_device in self.mdev_devices.values():
            output_file.write(
                "{}\t{}\t{}\n".format(mdev_device.uuid, mdev_device.pci_address, mdev_device.mdev_type.type)
            )

    def restore_mdev(self, input_file):
        result = 0
        for line in input_file:
            line = line.strip()
            comment_pos = line.find("#")
            if comment_pos != -1:
                line = line[:comment_pos]
            if line:
                mdev_reservation = line.split()
                if len(mdev_reservation) != 3:
                    raise InvalidMdevFileFormat(
                        "In mdev reservation file should be three components (UUID, PCI address, MDEV type) separated by spaces"
                    )
                uuid, pci_address, mdev_type_name = line.split()
                mdev_device = self.mdev_devices.get(uuid)
                if mdev_device:
                    LOG.warn("Mdev device with UUID %s already registred, ignoring", uuid)
                    continue
                mdev_device_class = self.mdev_device_classes.get(pci_address)
                if not mdev_device_class:
                    LOG.error("Mdev device class with PCI address %s does not exist", pci_address)
                    result = 1
                    continue
                LOG.info("Found device class %s", mdev_device_class)
                mdev_type = mdev_device_class.supported_mdev_types.get(mdev_type_name)
                if not mdev_type:
                    LOG.error(
                        "Mdev type with name %s does not exist in device class with PCI address %s and path %s",
                        mdev_type_name,
                        pci_address,
                        mdev_device_class.path,
                    )
                    result = 1
                    continue
                LOG.info("Found device type %s", mdev_type)
                if mdev_type.available_instances <= 0:
                    LOG.error(
                        "Mdev type with name %s does in device class with PCI address %s and path %s has no available instances",
                        mdev_type_name,
                        pci_address,
                        mdev_device_class.path,
                    )
                    result = 1
                    continue
                try:
                    mdev_type.create(uuid)
                except PermissionError as e:
                    LOG.exception(
                        "Could not register mdev type %s with device class with PCI address %s and path %s, try to run this command as root",
                        mdev_type_name,
                        pci_address,
                        mdev_device_class.path,
                    )
                    result = 1
                except OSError as e:
                    LOG.exception(
                        "Could not register mdev type %s with device class with PCI address %s and path %s",
                        mdev_type_name,
                        pci_address,
                        mdev_device_class.path,
                    )
                    result = 1
        return result


DEV_CTL = None


def list_pci(args):
    return DEV_CTL.print_pci_devices(pci_addresses_filter=args.pci_addresses)


def list_mdev(args):
    if args.classes:
        return DEV_CTL.print_mdev_device_classes(
            pci_addresses_filter=args.pci_addresses, mdev_types_filter=args.mdev_types
        )
    else:
        return DEV_CTL.print_mdev_devices(pci_addresses_filter=args.pci_addresses, mdev_types_filter=args.mdev_types)


def save_mdev(args):
    return DEV_CTL.save_mdev(output_file=args.output_file)


def restore_mdev(args):
    return DEV_CTL.restore_mdev(input_file=args.input_file)


def main():
    global DEV_CTL

    parser = argparse.ArgumentParser(
        description="NVIDIA Mdev Manager", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--debug", help="debug mode", action="store_true")
    parser.add_argument("-w", "--wait", help="wait until mdev bus is available", action="store_true")
    parser.add_argument("--trials", type=int, default=3, metavar="N", help="number of trials if waiting for device")
    parser.add_argument(
        "--delay",
        type=int,
        default=1,
        metavar="SECONDS",
        help="delay time in seconds between trials if waiting for device",
    )

    def register_list_pci_args(parser):
        parser.add_argument(
            "-p",
            "--pci-address",
            help="show only devices with specified pci addresses",
            action="append",
            dest="pci_addresses",
        )
        parser.set_defaults(func=list_pci)


    def register_list_mdev_args(parser):
        parser.add_argument("-c", "--classes", help="print mdev device classes", action="store_true")
        parser.add_argument(
            "-p",
            "--pci-address",
            help="show only devices with specified pci addresses",
            action="append",
            dest="pci_addresses",
        )
        parser.add_argument(
            "-m", "--mdev-type", help="show only devices with specified mdev types", action="append", dest="mdev_types",
        )
        parser.set_defaults(func=list_mdev)

    parser.set_defaults(subcommand="list-pci")
    register_list_pci_args(parser)

    subparsers = parser.add_subparsers(title="subcommands", dest="subcommand", metavar="")

    list_pci_p = subparsers.add_parser("list-pci", help="list NVIDIA PCI devices")
    register_list_pci_args(list_pci_p)

    list_mdev_p = subparsers.add_parser("list-mdev", help="list registered mdev devices")
    register_list_mdev_args(list_mdev_p)

    save_p = subparsers.add_parser("save", help="dump registered mdev devices")
    save_p.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="output mdev devices to file",
        type=argparse.FileType("w"),
        default=sys.stdout,
        dest="output_file",
    )
    save_p.set_defaults(func=save_mdev)

    restore_p = subparsers.add_parser("restore", help="restore registered mdev devices")
    restore_p.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        help="load mdev devices from file",
        type=argparse.FileType("r"),
        default=sys.stdin,
        dest="input_file",
    )
    restore_p.set_defaults(func=restore_mdev)

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(
            format="%(asctime)s %(levelname)s %(pathname)s:%(lineno)s: %(message)s", level=logging.DEBUG
        )
    else:
        logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)

    args = parser.parse_args()

    try:
        DEV_CTL = DevCtl(wait_for_device=args.wait, num_trials=args.trials, wait_delay=args.delay)
    except DevCtlException as e:
        logging.exception("Cloud not create DevCtl")
        return 1

    result = 0
    try:
        result = args.func(args)
    except DevCtlException as e:
        logging.exception("Could not execute {} command".format(args.subcommand))
        return 1
    if result is None:
        result = 0
    return result


if __name__ == "__main__":
    sys.exit(main())
