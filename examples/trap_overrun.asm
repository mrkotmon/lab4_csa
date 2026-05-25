; trap_overrun.asm — демонстрация однословного входного регистра без очереди.
.equ IO_IN 8184
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
    LI R1, IO_IN
    LW R2, 0(R1)
    HLT
