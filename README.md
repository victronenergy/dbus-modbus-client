# dbus-modbus-client

Reads data from Modbus devices and publishes on D-Bus.  Service names and
paths are per the [Victron D-Bus specification](https://github.com/victronenergy/venus/wiki/dbus).

Modbus devices using the RTU, TCP, and UDP transports are supported.

## VregLink

With some devices, the [VregLink](https://github.com/victronenergy/venus/wiki/dbus-api#the-vreglink-interface)
interface is supported.

The VregLink interface uses a block of up to 125 Modbus holding registers
accessed with the Modbus Read/Write Multiple Registers function (code 23).
Byte data is packed into 16-bit register values MSB first. All accesses
start from offset zero in the VregLink block. The base address is device
specific.

### Write

| Offset | Field   |
| ------ | ------- |
| 0      | VREG ID |
| 1      | Size    |
| 2..N   | Data    |

A write operation contains the VREG to access and, optionally, data for
setting the value. The size field indicates the length in bytes of the
data and must be 2x the number of registers or 1 less. To select a VREG
for a subsequent read, only the first field (VREG ID) should be present.

### Read

| Offset | Field   |
| ------ | ------- |
| 0      | VREG ID |
| 1      | Status  |
| 2      | Size    |
| 3..N   | Data    |

A read operation returns the value of the selected VREG or an error code if
the access failed. The size field indicates the length of the data in bytes.
The actual size of the VREG value is returned even if the requested number
of registers is too small to contain it.

### Status

The following status codes are possible.

| Value  | Meaning                      |
| ------ | ---------------------------- |
| 0      | Success                      |
| 0x8000 | Read: unknown error          |
| 0x8001 | Read: VREG does not exist    |
| 0x8002 | Read: VREG is write-only     |
| 0x8100 | Write: unknown error         |
| 0x8101 | Write: VREG does not exist   |
| 0x8102 | Write: VREG is read-only     |
| 0x8104 | Write: data invalid for VREG |

### Examples

If the VregLink register block begins at address 0x4000, then to read
VREG 0x100 (product ID), the following Modbus transaction would be used.

| Field Name                | Hex | Comment                       |
| ------------------------- | --- | ----------------------------- |
| _Request_                 |     |                               |
| Function                  | 17  | Read/Write Multiple Registers |
| Read Starting Address Hi  | 40  | VregLink base address         |
| Read Starting Address Lo  | 00  |                               |
| Quantity to Read Hi       | 00  |                               |
| Quantity to Read Lo       | 05  |                               |
| Write Starting Address Hi | 40  | VregLink base address         |
| Write Starting address Lo | 00  |                               |
| Quantity to Write Hi      | 00  |                               |
| Quantity to Write Lo      | 01  |                               |
| Write Byte Count          | 02  |                               |
| Write Register Hi         | 01  | PRODUCT_ID                    |
| Write Register Lo         | 00  |                               |
| _Response_                |     |                               |
| Function                  | 17  | Read/Write Multiple Registers |
| Byte Count                | 0A  |                               |
| Read Register Hi          | 01  | PRODUCT_ID                    |
| Read Register Lo          | 00  |                               |
| Read Register Hi          | 00  | Status: success               |
| Read Register Lo          | 00  |                               |
| Read Register Hi          | 00  | Size: 4                       |
| Read Register Lo          | 04  |                               |
| Read Register Hi          | 00  | Product ID                    |
| Read Register Lo          | 12  |                               |
| Read Register Hi          | 34  |                               |
| Read Register Lo          | FE  |                               |

To set VREG 0x10C (description), the Modbus transaction might look as
follows.

| Field Name                | Hex | Comment                       |
| ------------------------- | --- | ----------------------------- |
| _Request_                 |     |                               |
| Function                  | 17  | Read/Write Multiple Registers |
| Read Starting Address Hi  | 40  | VregLink base address         |
| Read Starting Address Lo  | 00  |                               |
| Quantity to Read Hi       | 00  |                               |
| Quantity to Read Lo       | 02  |                               |
| Write Starting Address Hi | 40  | VregLink base address         |
| Write Starting address Lo | 00  |                               |
| Quantity to Write Hi      | 00  |                               |
| Quantity to Write Lo      | 08  |                               |
| Write Byte Count          | 10  |                               |
| Write Register Hi         | 01  | DESCRIPTION1                  |
| Write Register Lo         | 0C  |                               |
| Write Register Hi         | 00  | Size: 11                      |
| Write Register Lo         | 0B  |                               |
| Write Register Hi         | 4D  | 'M'                           |
| Write Register Lo         | 79  | 'y'                           |
| Write Register Hi         | 20  | ' '                           |
| Write Register Lo         | 50  | 'P'                           |
| Write Register Hi         | 72  | 'r'                           |
| Write Register Lo         | 65  | 'e'                           |
| Write Register Hi         | 63  | 'c'                           |
| Write Register Lo         | 69  | 'i'                           |
| Write Register Hi         | 6f  | 'o'                           |
| Write Register Lo         | 75  | 'u'                           |
| Write Register Hi         | 73  | 's'                           |
| Write Register Lo         | 00  | Padding                       |
| _Response_                |     |                               |
| Function                  | 17  | Read/Write Multiple Registers |
| Byte Count                | 04  |                               |
| Read Register Hi          | 01  | DESCRIPTION1                  |
| Read Register Lo          | 0C  |                               |
| Read Register Hi          | 00  | Status: success               |
| Read Register Lo          | 00  |                               |
