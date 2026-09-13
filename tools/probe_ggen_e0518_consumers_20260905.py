#!/usr/bin/env python3
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
ROOT=Path(__file__).resolve().parents[1];r=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes();md=Cs(CS_ARCH_ARM,CS_MODE_THUMB);md.detail=False
for lit in [0x1de58,0x1e228,0x1e334,0x1ebe8,0x1ecc8,0x1edcc,0x1ee90,0x1ef64,0x1f094,0x1f34c,0x1f604,0x6bff8,0x6c194,0x6c3a4,0x6c6b0,0x6c918,0x6c9fc,0x6cb3c,0x6cc38,0x6cd14,0x6cddc,0x6ced8,0x6cfb8,0x6d1ec]:
 print('\nLITERAL',hex(0x08000000+lit))
 start=max(0,lit-96);end=min(len(r),lit+4)
 for ins in md.disasm(r[start:end],0x08000000+start):
  print(f'{ins.address:08X}: {ins.mnemonic:7} {ins.op_str}')
