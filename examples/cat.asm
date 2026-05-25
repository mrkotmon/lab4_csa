; cat.asm — поток символов обслуживается только обработчиком trap.
.equ IO_IN  8184
.equ IO_OUT 8188

.data
.org 0
    .word irq_handler

.text
.org 4
.entry _start
_start:
    EI
wait:
    JMP wait

irq_handler:
    LI  R1, IO_IN
    LW  R2, 0(R1)
    BEQ R2, R0, finish
    LI  R3, IO_OUT
    SW  R2, 0(R3)
    IRET
finish:
    HLT
