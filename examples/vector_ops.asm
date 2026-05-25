; vector_ops.asm — демонстрация полного минимального набора vector.
.equ IO_OUT 8188
.data
.org 1024
left:   .word 8,12,16,20
right:  .word 2,3,4,5
stored: .word 0,0,0,0
.text
.org 4
.entry _start
_start:
    LI    R1, left
    VLD   V0, 0(R1)
    LI    R1, right
    VLD   V1, 0(R1)
    VADD  V2, V0, V1
    VSUB  V2, V0, V1
    VMUL  V2, V0, V1
    VDIV  V2, V0, V1      ; [4,4,4,4]
    VCMP  V3, V2, V2      ; [1,1,1,1]
    LI    R1, stored
    VST   V2, 0(R1)
    VRED  R2, V3          ; 4 successful comparisons
    ADDI  R2, R2, 48
    LI    R3, IO_OUT
    SW    R2, 0(R3)
    LI    R2, 10
    SW    R2, 0(R3)
    HLT
