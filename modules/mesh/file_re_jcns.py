import struct
from dataclasses import dataclass, field

from ..hashing.mmh3.pymmh3 import hashUTF16

JCNS_VERSION = 22
JCNS_MAGIC = b"jcns"
JCNS_HEADER_SIZE = 0xC0
JCNS_RECORD_SIZE = 0x50
JCNS_CONDITION_SIZE = 0x48

class JCNSParseError(Exception):
    pass

@dataclass
class JCNSCondition:
    boneName: str
    boneHash: int
    axis: int
    flags: tuple
    knots: tuple
    values: tuple

@dataclass
class JCNSRecord:
    outputName: str
    outputHash: int
    conditionList: list = field(default_factory=list)

@dataclass
class JCNSFile:
    filePath: str
    recordList: list = field(default_factory=list)
    dependencyHashDict: dict = field(default_factory=dict)

def _requireRange(data, offset, size, label):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise JCNSParseError(f"{label} is outside the file: offset=0x{offset:X}, size=0x{size:X}")

def _unpack(data, formatString, offset, label):
    size = struct.calcsize(formatString)
    _requireRange(data, offset, size, label)
    return struct.unpack_from(formatString, data, offset)

def _readUTF16(data, offset, label):
    if offset == 0 or offset % 2:
        raise JCNSParseError(f"{label} has invalid string offset 0x{offset:X}")
    
    endOffset = offset
    while True:
        _requireRange(data, endOffset, 2, label)
        if data[endOffset:endOffset + 2] == b"\x00\x00":
            break
        endOffset += 2
    
    try:
        return data[offset:endOffset].decode("utf-16le")
    except UnicodeDecodeError as error:
        raise JCNSParseError(f"{label} is not valid UTF-16LE") from error

def _validateHash(name, storedHash, label):
    calculatedHash = hashUTF16(name) & 0xFFFFFFFF
    if calculatedHash != storedHash:
        raise JCNSParseError(f"{label} hash mismatch: stored=0x{storedHash:08X}, calculated=0x{calculatedHash:08X}")