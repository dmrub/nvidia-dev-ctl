# nvidia-dev-ctl.py
Control tool for NVIDIA GPU and vGPU devices

```
usage: nvidia-dev-ctl.py [-h] [--debug] [-w] [--trials N] [--delay SECONDS]
                         [-p PCI_ADDRESSES]
                         ...

NVIDIA Mdev Manager

optional arguments:
  -h, --help            show this help message and exit
  --debug               debug mode (default: False)
  -w, --wait            wait until mdev bus is available (default: False)
  --trials N            number of trials if waiting for device (default: 3)
  --delay SECONDS       delay time in seconds between trials if waiting for
                        device (default: 1)
  -p PCI_ADDRESSES, --pci-address PCI_ADDRESSES
                        show only devices with specified pci addresses
                        (default: None)

subcommands:

    list-pci            list NVIDIA PCI devices
    list-mdev           list registered mdev devices
    save                dump registered mdev devices
    restore             restore registered mdev devices
```

## list-pci command

```
usage: nvidia-dev-ctl.py list-pci [-h] [-p PCI_ADDRESSES]

optional arguments:
  -h, --help            show this help message and exit
  -p PCI_ADDRESSES, --pci-address PCI_ADDRESSES
                        show only devices with specified pci addresses
```

## list-mdev command

```
usage: nvidia-dev-ctl.py list-mdev [-h] [-c] [-p PCI_ADDRESSES]
                                   [-m MDEV_TYPES]

optional arguments:
  -h, --help            show this help message and exit
  -c, --classes         print mdev device classes
  -p PCI_ADDRESSES, --pci-address PCI_ADDRESSES
                        show only devices with specified pci addresses
  -m MDEV_TYPES, --mdev-type MDEV_TYPES
                        show only devices with specified mdev types
```

## save command

```
usage: nvidia-dev-ctl.py save [-h] [-o FILE]

optional arguments:
  -h, --help            show this help message and exit
  -o FILE, --output FILE
                        output mdev devices to file
```

## restore command

```
usage: nvidia-dev-ctl.py restore [-h] [-i FILE]

optional arguments:
  -h, --help            show this help message and exit
  -i FILE, --input FILE
                        load mdev devices from file
```
