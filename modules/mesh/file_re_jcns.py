# Author: TrueShadow01

import math
import os
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
    curveModeRaw: int
    flags: tuple
    inputValues: tuple
    outputValues: tuple

@dataclass
class JCNSRecord:
    outputName: str
    outputHash: int
    conditionList: list = field(default_factory=list)
    rawMetadata: bytes = b""

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
    
def _readHeader(data):
    _requireRange(data, 0, JCNS_HEADER_SIZE, "JCNS header")
    version, = _unpack(data, "<I", 0x00, "JCNS version")
    magic, = _unpack(data, "<4s", 0x04, "JCNS magic")
    if version != JCNS_VERSION or magic != JCNS_MAGIC:
        raise JCNSParseError(f"Unsupported JCNS header: version={version}, magic={magic}")
    
    backingOffset, recordOffset = _unpack(data, "<QQ", 0x50, "record offsets")
    footerOffset, = _unpack(data, "<Q", 0x60, "footer offset")
    footerOffsetCopy, graphOffset = _unpack(data, "<QQ", 0x90, "footer and graph offsets")
    recordCount, outputCount = _unpack(data, "<HI", 0xA2, "record counts")

    if backingOffset != JCNS_HEADER_SIZE:
        raise JCNSParseError("JCNS has an invalid backing offset")
    if footerOffset != footerOffsetCopy:
        raise JCNSParseError("JCNS footer offsets do not match")
    if any(offset % 0x10 for offset in (backingOffset, recordOffset, footerOffset, graphOffset) if offset):
        raise JCNSParseError("JCNS contains an unaligned section offset")
    
    if recordCount:
        if recordOffset != backingOffset:
            raise JCNSParseError("JCNS record offsets do not match")
        if not 0 < outputCount <= recordCount:
            raise JCNSParseError("JCNS has inconsistent record counts")
        if not graphOffset:
            raise JCNSParseError("JCNS dependency table is missing")
        if recordOffset + recordCount * JCNS_RECORD_SIZE > graphOffset:
            raise JCNSParseError("JCNS record table overlaps later data")
        if graphOffset + outputCount * 0x10 > footerOffset:
            raise JCNSParseError("JCNS dependency table overlaps the footer")
    elif recordOffset or graphOffset or outputCount:
        raise JCNSParseError("Empty JCNS contains populated table fields")

    _requireRange(data, recordOffset, recordCount * JCNS_RECORD_SIZE, "record table")
    _requireRange(data, footerOffset, 0x14, "footer")

    if footerOffset + 0x14 != len(data):
        raise JCNSParseError("JCNS footer is not at the end of the file")
    if outputCount:
        _requireRange(data, graphOffset, outputCount * 0x10, "dependency table")

    return recordOffset, graphOffset, recordCount, outputCount

def _readCondition(data, conditionOffset, label):
    boneNameOffset, = _unpack(data, "<Q", conditionOffset + 0x08, f"{label} bone name pointer")
    boneHash, = _unpack(data, "<I", conditionOffset + 0x10, f"{label} bone hash")
    flagA, curveModeRaw, axis, flagB = _unpack(data, "<4B", conditionOffset + 0x18, f"{label} metadata")
    conditionFlags, = _unpack(data, "<I", conditionOffset + 0x1C, f"{label} flags")
    if axis > 2:
        raise JCNSParseError(f"{label} has invalid axis {axis}")
    
    boneName = _readUTF16(data, boneNameOffset, f"{label} bone name")
    _validateHash(boneName, boneHash, f"{label} bone")
    inputValues = _unpack(data, "<3f", conditionOffset + 0x20, f"{label} inputs")
    outputValues = _unpack(data, "<3f", conditionOffset + 0x2C, f"{label} outputs")
    tailValues = _unpack(data, "<4f", conditionOffset + 0x38, f"{label} tail")

    if not all(math.isfinite(value) for value in inputValues + outputValues):
        raise JCNSParseError(f"{label} contains non-finite curve data")
    if tailValues != (0.0, 0.0, 0.0, 1.0):
        raise JCNSParseError(f"{label} has an unsupported condition tail")
    
    return JCNSCondition(boneName, boneHash, axis, curveModeRaw, (flagA, flagB, conditionFlags), inputValues, outputValues)

def _readRecord(data, recordOffset, recordIndex):
    label = f"record {recordIndex}"
    conditionOffset, = _unpack(data, "<Q", recordOffset + 0x08, f"{label} condition pointer")
    outputNameOffset, = _unpack(data, "<Q", recordOffset + 0x10, f"{label} output name pointer")
    outputHash, = _unpack(data, "<I", recordOffset + 0x20, f"{label} output hash")
    conditionCount, = _unpack(data, "<B", recordOffset + 0x29, f"{label} condition count")

    if conditionCount:
        if not conditionOffset:
            raise JCNSParseError(f"{label} has no condition pointer")
        _requireRange(data, conditionOffset, conditionCount * JCNS_CONDITION_SIZE, f"{label} condition block")
    elif conditionOffset:
        raise JCNSParseError(f"{label} has a condition pointer but no conditions")
    
    outputName = _readUTF16(data, outputNameOffset, f"{label} output name")
    _validateHash(outputName, outputHash, f"{label} output")

    record = JCNSRecord(outputName, outputHash)
    record.rawMetadata = data[recordOffset + 0x28:recordOffset + JCNS_RECORD_SIZE]

    for conditionIndex in range(conditionCount):
        currentOffset = (conditionOffset + conditionIndex * JCNS_CONDITION_SIZE)
        record.conditionList.append(_readCondition(data, currentOffset, f"{label} condition {conditionIndex}"))

    return record

def _readDependencyTable(data, graphOffset, outputCount, outputHashSet):
    dependencyHashDict = {}

    for graphIndex in range(outputCount):
        label = f"dependency {graphIndex}"
        entryOffset = graphOffset + graphIndex * 0x10
        dependencyOffset, sourceCount = _unpack(data, "<QQ", entryOffset, f"{label} entry")

        if not dependencyOffset:
            raise JCNSParseError(f"{label} has no hash list pointer")
        
        _requireRange(data, dependencyOffset, 4 + sourceCount * 4, f"{label} hashes")
        outputHash, = _unpack(data, "<I", dependencyOffset, f"{label} output hash")

        if outputHash not in outputHashSet:
            raise JCNSParseError(f"{label} references unknown output 0x{outputHash:08X}")
        if outputHash in dependencyHashDict:
            raise JCNSParseError(f"{label} duplicates output 0x{outputHash:08X}")
        
        if sourceCount:
            sourceHashes = _unpack(data, f"<{sourceCount}I", dependencyOffset + 4, f"{label} source hashes")
        else:
            sourceHashes = ()
        
        dependencyHashDict[outputHash] = sourceHashes
    return dependencyHashDict

def readJCNS(filePath):
    try:
        with open(filePath, "rb") as file:
            data = file.read()
    except OSError as error:
        raise JCNSParseError(f"Failed to open JCNS file: {filePath}") from error
    
    recordOffset, graphOffset, recordCount, outputCount = _readHeader(data)
    recordList = [_readRecord(data, recordOffset + recordIndex * JCNS_RECORD_SIZE, recordIndex) for recordIndex in range(recordCount)]

    outputHashSet = {record.outputHash for record in recordList}
    if len(outputHashSet) != outputCount:
        raise JCNSParseError("JCNS unique output count does not match its records")
    
    dependencyHashDict = _readDependencyTable(data, graphOffset, outputCount, outputHashSet)
    return JCNSFile(filePath, recordList, dependencyHashDict)

def findJCNSPath(meshFilePath):
    if not meshFilePath:
        return None
    
    fileName = os.path.basename(meshFilePath)
    meshMarkerIndex = fileName.lower().find(".mesh")
    if meshMarkerIndex == -1:
        return None
    
    meshBaseName = fileName[:meshMarkerIndex]
    meshDirectory = os.path.dirname(meshFilePath)
    directoryName = os.path.basename(meshDirectory)

    # Meshes normally live under numbered component dir
    # e.g. 00, 01, 02, JCNS files sit one dir above
    if len(directoryName) == 2 and directoryName.isdigit():
        jcnsDirectory = os.path.dirname(meshDirectory)
    else:
        jcnsDirectory = meshDirectory
    
    exactPath = os.path.join(jcnsDirectory, f"{meshBaseName}_drv_bs1.jcns.22")
    if os.path.isfile(exactPath):
        return exactPath
    
    # some use a shared JCNS file for head, body and other component meshes
    nameParts = meshBaseName.rsplit("_", 1)
    if (len(nameParts) == 2 and len(nameParts[1]) == 2 and nameParts[1].isdigit()):
        sharedPath = os.path.join(jcnsDirectory, f"{nameParts[0]}_drv_bs1.jcns.22")
        if os.path.isfile(sharedPath):
            return sharedPath
    
    return None