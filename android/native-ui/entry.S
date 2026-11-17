.section .text.entry,"ax"
.global melka_full_entry
.global melka_plain_entry
.global old_full
.global old_plain
melka_full_entry:
    stp x29, x30, [sp, #-16]!
    adrp x1, melka_full_entry
    add x1, x1, :lo12:melka_full_entry
    mov x2, #0x1000
    movk x2, #0x7a8, lsl #16
    sub x1, x1, x2
    mov w2, #0
    bl melka_ui
    ldp x29, x30, [sp], #16
    ret
melka_plain_entry:
    stp x29, x30, [sp, #-16]!
    adrp x1, melka_full_entry
    add x1, x1, :lo12:melka_full_entry
    mov x2, #0x1000
    movk x2, #0x7a8, lsl #16
    sub x1, x1, x2
    mov w2, #1
    bl melka_ui
    ldp x29, x30, [sp], #16
    ret
old_full:
    sub sp, sp, #0x70
    b original_full_body
old_plain:
    sub sp, sp, #0x70
    b original_plain_body
