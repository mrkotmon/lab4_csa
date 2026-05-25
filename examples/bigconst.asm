; bigconst.asm — макросы, константы и условная компиляция ASM.
.equ IO_OUT 8188
.equ USE_A  1

.macro PUT reg
    SW reg, 0(R2)
.endm

.text
.org 4
.entry _start
_start:
    LI R2, IO_OUT
.if USE_A
    LI R1, 65
.else
    LI R1, 66
.endif
    PUT R1
    LI R1, 10
    PUT R1
    HLT
