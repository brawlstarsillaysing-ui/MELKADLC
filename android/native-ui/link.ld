original_full_body = 0x7a7e838;
original_plain_body = 0x7a7ea9c;
SECTIONS {
  . = 0x7a81000;
  .text : { KEEP(*(.text.entry)) KEEP(*(.text*)) }
  .rodata : { KEEP(*(.rodata*)) }
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
