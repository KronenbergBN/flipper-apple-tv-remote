"""Run the actual input handler against SDK enums with a stub HID transport."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get("UFBT_HOME", Path.home() / ".ufbt")) / "current/sdk_headers/f7_sdk"
source = (root / "apple_tv_remote.c").read_text()
handler = source[source.index("static bool remote_handle_input("):source.index("int32_t apple_tv_remote_app(")]

def sdk_enum(path, name):
    text = (sdk / path).read_text()
    return re.search(r"typedef enum \{[^}]*\} " + name + r";", text).group()

code = r"""
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <hid_usage_keyboard.h>
#include <hid_usage_consumer.h>
"""
code += sdk_enum("targets/f7/furi_hal/furi_hal_resources.h", "InputKey")
code += sdk_enum("applications/services/input/input.h", "InputType")
code += r"""
typedef struct { InputKey key; InputType type; } InputEvent;
typedef struct {
    int lock, view_port;
    void* profile;
    struct { bool connected, highlight, actions; uint8_t action; InputKey last_key; } screen;
    uint32_t highlight_until;
} Remote;
#define FuriWaitForever 0
#define furi_mutex_acquire(...) ((void)0)
#define furi_mutex_release(...) ((void)0)
#define view_port_update(...) ((void)0)
#define furi_get_tick() 0
#define furi_ms_to_ticks(x) (x)
static uint16_t last_code;
static bool last_consumer;
static unsigned pulses;
static bool remote_pulse(Remote* app, uint16_t code, bool consumer) {
    (void)app; last_code=code; last_consumer=consumer; pulses++; return true;
}
"""
code += handler
code += r"""
int main(void) {
    Remote app = {.profile=(void*)1, .screen.connected=true};
    const InputKey keys[] = {InputKeyUp, InputKeyDown, InputKeyLeft, InputKeyRight};
    const uint16_t codes[] = {0x52, 0x51, 0x50, 0x4f};
    for(unsigned i=0;i<4;i++) {
        InputEvent event = {.key=keys[i], .type=InputTypePress};
        unsigned before=pulses;
        assert(remote_handle_input(&app, &event));
        if(pulses!=before+1 || last_code!=codes[i] || last_consumer) {
            fprintf(stderr, "Direction failed: key=%u expected HID=%u\n", keys[i],codes[i]);
            return 1;
        }
        event.type=InputTypeShort;
        remote_handle_input(&app,&event);
        assert(pulses==before+1); /* no duplicate on release */
        event.type=InputTypeRepeat;
        remote_handle_input(&app,&event);
        assert(pulses==before+2 && last_code==codes[i]);
    }
    InputEvent event={.key=InputKeyOk,.type=InputTypePress};
    unsigned before=pulses;
    remote_handle_input(&app,&event);
    assert(pulses==before); /* wait to distinguish short from long */
    event.type=InputTypeShort;
    remote_handle_input(&app,&event);
    assert(pulses==before+1 && last_code==0x28 && !last_consumer);
    event.type=InputTypeLong;
    remote_handle_input(&app,&event);
    assert(pulses==before+1 && app.screen.actions); /* menu only, never select */
    event.type=InputTypeRepeat;
    remote_handle_input(&app,&event);
    assert(pulses==before+1); /* held OK cannot activate a menu item */
    event.type=InputTypeShort;
    remote_handle_input(&app,&event);
    assert(pulses==before+2 && last_code==0xcd && last_consumer && !app.screen.actions);
    event.type=InputTypeLong; remote_handle_input(&app,&event);
    event.key=InputKeyDown; event.type=InputTypePress; remote_handle_input(&app,&event);
    event.key=InputKeyOk; event.type=InputTypeShort; remote_handle_input(&app,&event);
    assert(pulses==before+3 && last_code==0x28 && !last_consumer);
    event.type=InputTypeLong; remote_handle_input(&app,&event);
    event.key=InputKeyDown; event.type=InputTypePress;
    remote_handle_input(&app,&event); remote_handle_input(&app,&event);
    assert(pulses==before+3 && app.screen.action==2); /* selection cannot send Power */
    event.key=InputKeyOk; event.type=InputTypeShort; remote_handle_input(&app,&event);
    assert(pulses==before+4 && last_code==0x30 && last_consumer && !app.screen.actions);
    event.type=InputTypeRepeat; remote_handle_input(&app,&event);
    assert(pulses==before+4); /* Power exactly once */
    event.type=InputTypeLong; remote_handle_input(&app,&event);
    event.key=InputKeyBack; event.type=InputTypeShort; remote_handle_input(&app,&event);
    assert(pulses==before+4 && !app.screen.actions); /* cancel sends nothing */
    event.key=InputKeyBack; event.type=InputTypeShort;
    remote_handle_input(&app,&event);
    assert(last_code==0x29 && !last_consumer);
    before=pulses;
    event.type=InputTypeLong;
    assert(remote_handle_input(&app,&event)); /* long Back must keep the app open */
    assert(pulses==before+1 && last_code==0x30 && last_consumer);
    event.type=InputTypeRepeat;
    remote_handle_input(&app,&event);
    event.type=InputTypeRelease;
    remote_handle_input(&app,&event);
    assert(pulses==before+1); /* no repeat Power or Escape after a hold */
    event.key=InputKeyOk; event.type=InputTypeLong;
    remote_handle_input(&app,&event);
    event.key=InputKeyBack; event.type=InputTypeLong;
    assert(remote_handle_input(&app,&event) && pulses==before+2 && last_code==0x30);
    event.type=InputTypeShort;
    remote_handle_input(&app,&event); /* dismiss Actions, no TV command */
    before=pulses;
    app.screen.connected=false;
    event.key=InputKeyLeft; event.type=InputTypePress;
    assert(remote_handle_input(&app,&event) && pulses==before);
    event.key=InputKeyBack; event.type=InputTypeLong;
    assert(remote_handle_input(&app,&event) && pulses==before);
    /* Exit remains reachable while disconnected or when profile startup failed. */
    app.profile=0;
    event.key=InputKeyOk; event.type=InputTypeLong;
    assert(remote_handle_input(&app,&event) && app.screen.actions);
    event.key=InputKeyUp; event.type=InputTypePress;
    remote_handle_input(&app,&event);
    assert(app.screen.action==3);
    event.key=InputKeyOk; event.type=InputTypeShort;
    assert(!remote_handle_input(&app,&event) && pulses==before);
    /* Connected Exit must also send no command. */
    app.profile=(void*)1; app.screen.connected=true;
    app.screen.actions=true; app.screen.action=3;
    assert(!remote_handle_input(&app,&event) && pulses==before);
    puts("PASS: directions, repeat, Back hold Power without exit, no repeat Power, menu Exit online/offline");
}
"""
with tempfile.TemporaryDirectory(prefix="flipper-controls-") as tmp:
    test = Path(tmp) / "controls.c"
    binary = Path(tmp) / "controls"
    test.write_text(code)
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I",
                    str(sdk / "lib/libusb_stm32/inc"), str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
