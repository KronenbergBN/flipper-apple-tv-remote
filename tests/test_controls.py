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
    struct { bool connected, highlight, actions, volume; uint8_t action; InputKey last_key; } screen;
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
static bool input(Remote* app, InputKey key, InputType type) {
    InputEvent e={.key=key,.type=type}; return remote_handle_input(app,&e);
}
static bool choose(Remote* app, unsigned index) {
    if(app->screen.actions) assert(input(app,InputKeyBack,InputTypeShort));
    assert(input(app,InputKeyOk,InputTypeLong));
    assert(app->screen.actions && app->screen.action==0);
    for(unsigned i=0;i<index;i++) assert(input(app,InputKeyDown,InputTypePress));
    return input(app,InputKeyOk,InputTypeShort);
}
int main(void) {
    Remote app={.profile=(void*)1,.screen.connected=true};
    const InputKey keys[]={InputKeyUp,InputKeyDown,InputKeyLeft,InputKeyRight};
    const uint16_t codes[]={0x52,0x51,0x50,0x4f};
    for(unsigned i=0;i<4;i++) {
        unsigned before=pulses;
        assert(input(&app,keys[i],InputTypePress));
        assert(pulses==before+1 && last_code==codes[i] && !last_consumer);
        input(&app,keys[i],InputTypeShort);
        input(&app,keys[i],InputTypeRelease);
        assert(pulses==before+1);
        input(&app,keys[i],InputTypeRepeat);
        assert(pulses==before+2);
    }
    input(&app,InputKeyOk,InputTypeShort);
    assert(last_code==0x28 && !last_consumer);
    input(&app,InputKeyBack,InputTypeShort);
    assert(last_code==0x29 && !last_consumer);
    unsigned before=pulses;
    input(&app,InputKeyBack,InputTypeLong);
    assert(pulses==before+1 && last_code==0x30 && last_consumer);
    input(&app,InputKeyBack,InputTypeRepeat);
    input(&app,InputKeyBack,InputTypeRelease);
    assert(pulses==before+1);
    assert(choose(&app,1) && last_code==0xcd && last_consumer);
    assert(choose(&app,2) && last_code==0x28 && !last_consumer);
    assert(choose(&app,3) && last_code==0x30 && last_consumer);
    before=pulses;
    input(&app,InputKeyOk,InputTypeRepeat);
    assert(pulses==before);
    assert(choose(&app,0) && app.screen.volume && !app.screen.actions);
    assert(pulses==before); /* entering Volume sends nothing */
    for(unsigned i=0;i<2;i++) {
        before=pulses;
        input(&app,keys[i],InputTypePress);
        assert(pulses==before+1 && last_code==(i ? 0xea : 0xe9) && last_consumer);
        input(&app,keys[i],InputTypeShort);
        input(&app,keys[i],InputTypeRelease);
        assert(pulses==before+1);
        input(&app,keys[i],InputTypeRepeat);
        assert(pulses==before+2);
    }
    before=pulses;
    input(&app,InputKeyLeft,InputTypePress);
    input(&app,InputKeyRight,InputTypeRepeat);
    assert(pulses==before); /* no accidental Apple TV navigation in Volume */
    input(&app,InputKeyOk,InputTypePress);
    assert(pulses==before);
    input(&app,InputKeyOk,InputTypeShort);
    assert(pulses==before+1 && last_code==0xe2 && last_consumer);
    input(&app,InputKeyOk,InputTypeRepeat);
    input(&app,InputKeyOk,InputTypeRelease);
    assert(pulses==before+1); /* mute toggles exactly once */
    input(&app,InputKeyOk,InputTypeLong);
    assert(app.screen.actions && pulses==before+1); /* long OK does not mute */
    input(&app,InputKeyBack,InputTypeShort);
    assert(!app.screen.actions && app.screen.volume && pulses==before+1);
    input(&app,InputKeyBack,InputTypeLong);
    assert(app.screen.volume && pulses==before+2 && last_code==0x30);
    before=pulses;
    input(&app,InputKeyBack,InputTypeShort);
    assert(!app.screen.volume && pulses==before); /* local return, not Escape */
    input(&app,InputKeyUp,InputTypePress);
    assert(last_code==0x52 && !last_consumer); /* navigation restored */
    assert(choose(&app,0));
    app.screen.connected=false;
    before=pulses;
    input(&app,InputKeyUp,InputTypePress);
    input(&app,InputKeyDown,InputTypeRepeat);
    input(&app,InputKeyOk,InputTypeShort);
    input(&app,InputKeyBack,InputTypeLong);
    assert(pulses==before);
    input(&app,InputKeyBack,InputTypeShort);
    assert(!app.screen.volume && pulses==before);
    app.profile=0;
    assert(!choose(&app,4) && pulses==before); /* offline Exit */
    app.profile=(void*)1; app.screen.connected=true;
    assert(!choose(&app,4) && pulses==before); /* online Exit */
    input(&app,InputKeyOk,InputTypeLong);
    input(&app,InputKeyUp,InputTypePress);
    assert(app.screen.action==4); /* menu wraps across five entries */
    input(&app,InputKeyBack,InputTypeShort);
    assert(pulses==before && !app.screen.actions);
    /* A disconnected main screen must not trap Back; long Back always exits
     * locally in Actions, even while connected, without sending Power. */
    app.screen.connected=false;
    app.screen.volume=false;
    assert(!input(&app,InputKeyBack,InputTypeShort));
    assert(!input(&app,InputKeyBack,InputTypeLong));
    app.profile=0;
    assert(!input(&app,InputKeyBack,InputTypeShort));
    assert(!input(&app,InputKeyBack,InputTypeLong));
    for(unsigned online=0; online<2; online++) {
        app.profile=online ? (void*)1 : 0;
        app.screen.connected=online;
        input(&app,InputKeyOk,InputTypeLong);
        before=pulses;
        assert(!input(&app,InputKeyBack,InputTypeLong));
        assert(pulses==before); /* local Exit never powers off the TV */
        assert(input(&app,InputKeyBack,InputTypeShort));
        assert(!app.screen.actions && pulses==before); /* cancel still works */
    }
    puts("PASS: navigation, volume repeat, single mute, mode changes, Power retained, offline handling, menu Exit");
}

"""
with tempfile.TemporaryDirectory(prefix="flipper-controls-") as tmp:
    test = Path(tmp) / "controls.c"
    binary = Path(tmp) / "controls"
    test.write_text(code)
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I",
                    str(sdk / "lib/libusb_stm32/inc"), str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
