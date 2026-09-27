// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Hanns Kronenberg

#include <furi.h>
#include <furi_hal_bt.h>
#include <furi_hal_usb_hid.h>
#include <bt/bt_service/bt.h>
#include <extra_profiles/hid_profile.h>
#include <gui/gui.h>
#include <gui/view_port.h>
#include <input/input.h>
#include <storage/storage.h>

/* Same HID identity and bond store as the official Bluetooth Remote app.
 * This retains the pairing the owner has just approved on their Apple TV.
 * No credentials are exported, erased or printed. */
#define REMOTE_BOND_DIR  EXT_PATH("apps_data/hid_ble")
#define REMOTE_BOND_PATH REMOTE_BOND_DIR "/.bt_hid.keys"

typedef struct {
    bool connected;
    bool failed;
    bool highlight;
    bool actions;
    uint8_t action;
    InputKey last_key;
} RemoteScreen;

typedef struct {
    Gui* gui;
    Bt* bt;
    ViewPort* view_port;
    FuriMessageQueue* input;
    FuriMutex* lock;
    FuriHalBleProfileBase* profile;
    RemoteScreen screen;
    uint32_t highlight_until;
} Remote;

static void remote_button(Canvas* canvas, int x, int y, InputKey key, bool selected) {
    if(selected) {
        canvas_draw_rbox(canvas, x, y, 20, 12, 2);
        canvas_set_color(canvas, ColorWhite);
    } else {
        canvas_draw_rframe(canvas, x, y, 20, 12, 2);
    }
    const int cx = x + 10;
    const int cy = y + 6;
    /* Pixel arrows stay unambiguous in the tiny display font. */
    switch(key) {
    case InputKeyUp:
        canvas_draw_line(canvas, cx, cy + 3, cx, cy - 3);
        canvas_draw_line(canvas, cx, cy - 3, cx - 3, cy);
        canvas_draw_line(canvas, cx, cy - 3, cx + 3, cy);
        break;
    case InputKeyDown:
        canvas_draw_line(canvas, cx, cy - 3, cx, cy + 3);
        canvas_draw_line(canvas, cx, cy + 3, cx - 3, cy);
        canvas_draw_line(canvas, cx, cy + 3, cx + 3, cy);
        break;
    case InputKeyLeft:
        canvas_draw_line(canvas, cx + 3, cy, cx - 3, cy);
        canvas_draw_line(canvas, cx - 3, cy, cx, cy - 3);
        canvas_draw_line(canvas, cx - 3, cy, cx, cy + 3);
        break;
    case InputKeyRight:
        canvas_draw_line(canvas, cx - 3, cy, cx + 3, cy);
        canvas_draw_line(canvas, cx + 3, cy, cx, cy - 3);
        canvas_draw_line(canvas, cx + 3, cy, cx, cy + 3);
        break;
    default:
        canvas_draw_str_aligned(canvas, cx, cy, AlignCenter, AlignCenter, "OK");
        break;
    }
    canvas_set_color(canvas, ColorBlack);
}

static void remote_draw(Canvas* canvas, void* context) {
    Remote* app = context;
    furi_mutex_acquire(app->lock, FuriWaitForever);
    RemoteScreen screen = app->screen;
    furi_mutex_release(app->lock);

    canvas_clear(canvas);
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 2, 10, "Apple TV");
    canvas_set_font(canvas, FontSecondary);
    canvas_draw_str_aligned(
        canvas, 126, 10, AlignRight, AlignBottom, screen.connected ? "Connected" : "Waiting...");
    canvas_draw_line(canvas, 0, 13, 127, 13);

    if(screen.actions) {
        const char* labels[] = {"Play / Pause", "Wake (OK)", "Power hold", "Exit app"};
        for(uint8_t i = 0; i < 4; i++) {
            int y = 16 + i * 10;
            if(screen.action == i) {
                canvas_draw_box(canvas, 1, y - 1, 126, 10);
                canvas_set_color(canvas, ColorWhite);
            }
            canvas_draw_str(canvas, 5, y + 7, labels[i]);
            canvas_set_color(canvas, ColorBlack);
        }
    } else if(screen.failed) {
        canvas_draw_str(canvas, 2, 28, "Bluetooth unavailable");
        canvas_draw_str(canvas, 2, 40, "Please restart app");
    } else if(!screen.connected) {
        canvas_draw_str(canvas, 2, 27, "Apple TV > Bluetooth");
        canvas_draw_str(canvas, 2, 39, "Select Control + name");
        canvas_draw_str(canvas, 2, 51, "Same code? Press OK");
    } else {
        remote_button(
            canvas, 23, 16, InputKeyUp, screen.highlight && screen.last_key == InputKeyUp);
        remote_button(
            canvas, 2, 29, InputKeyLeft, screen.highlight && screen.last_key == InputKeyLeft);
        remote_button(
            canvas, 23, 29, InputKeyOk, screen.highlight && screen.last_key == InputKeyOk);
        remote_button(
            canvas, 44, 29, InputKeyRight, screen.highlight && screen.last_key == InputKeyRight);
        remote_button(
            canvas, 23, 42, InputKeyDown, screen.highlight && screen.last_key == InputKeyDown);
        canvas_draw_str(canvas, 69, 24, "OK: Select");
        canvas_draw_str(canvas, 69, 34, "Back: Menu");
        canvas_draw_str(canvas, 69, 45, "Hold OK:");
        canvas_draw_str(canvas, 69, 54, "Actions");
    }
    canvas_draw_str_aligned(
        canvas,
        64,
        63,
        AlignCenter,
        AlignBottom,
        screen.actions   ? "Back: cancel  OK: run" :
        screen.connected ? "Hold Back: Power" :
                           "Hold OK: Actions / Exit");
}

static void remote_input(InputEvent* event, void* context) {
    Remote* app = context;
    /* Every outgoing command is a complete press/release pulse. Dropping a
     * repeat when the queue is full cannot leave a held key on the host. */
    if(event->type != InputTypeRelease) furi_message_queue_put(app->input, event, 0);
}

static void remote_bt_status(BtStatus status, void* context) {
    Remote* app = context;
    furi_mutex_acquire(app->lock, FuriWaitForever);
    app->screen.connected = status == BtStatusConnected;
    app->screen.highlight = false;
    furi_mutex_release(app->lock);
    view_port_update(app->view_port);
}

static bool remote_pulse(Remote* app, uint16_t code, bool consumer) {
    bool sent;
    if(consumer) {
        sent = ble_profile_hid_consumer_key_press(app->profile, code);
        furi_delay_ms(code == HID_CONSUMER_POWER ? 2000 : 60);
        ble_profile_hid_consumer_key_release_all(app->profile);
    } else {
        sent = ble_profile_hid_kb_press(app->profile, code);
        furi_delay_ms(60);
        ble_profile_hid_kb_release_all(app->profile);
    }
    return sent;
}

static bool remote_handle_input(Remote* app, const InputEvent* event) {
    furi_mutex_acquire(app->lock, FuriWaitForever);
    bool connected = app->screen.connected;
    bool actions = app->screen.actions;
    uint8_t action = app->screen.action;
    furi_mutex_release(app->lock);
    /* Hold Back is the owner's Power shortcut, never a local app exit.
     * Repeat and release events do not send an additional command. */
    if(event->key == InputKeyBack && event->type == InputTypeLong) {
        if(connected && app->profile) remote_pulse(app, HID_CONSUMER_POWER, true);
        return true;
    }

    uint16_t code = 0;
    bool consumer = false;
    if(event->key == InputKeyOk && event->type == InputTypeLong && !actions) {
        furi_mutex_acquire(app->lock, FuriWaitForever);
        app->screen.actions = true;
        app->screen.action = 0;
        furi_mutex_release(app->lock);
        view_port_update(app->view_port);
        return true;
    }
    if(actions) {
        if((event->key == InputKeyUp || event->key == InputKeyDown) &&
           (event->type == InputTypePress || event->type == InputTypeRepeat)) {
            furi_mutex_acquire(app->lock, FuriWaitForever);
            app->screen.action = (action + (event->key == InputKeyDown ? 1 : 3)) % 4;
            furi_mutex_release(app->lock);
            view_port_update(app->view_port);
            return true;
        }
        if(event->type != InputTypeShort ||
           (event->key != InputKeyOk && event->key != InputKeyBack))
            return true;
        furi_mutex_acquire(app->lock, FuriWaitForever);
        app->screen.actions = false;
        furi_mutex_release(app->lock);
        view_port_update(app->view_port);
        if(event->key == InputKeyBack) return true;
        if(action == 3) return false; /* Explicit Exit works even without Bluetooth. */
        if(!connected || !app->profile) return true;
        code = action == 0 ? HID_CONSUMER_PLAY_PAUSE :
               action == 1 ? HID_KEYBOARD_RETURN :
                             HID_CONSUMER_POWER;
        consumer = action != 1;
        /* Power confirmed on the owner's setup; compatibility with others may differ. */
        remote_pulse(app, code, consumer);
        return true;
    }
    if(!connected || !app->profile) return true;
    const bool direction = event->key == InputKeyUp || event->key == InputKeyDown ||
                           event->key == InputKeyLeft || event->key == InputKeyRight;
    if(direction && (event->type == InputTypePress || event->type == InputTypeRepeat)) {
        switch(event->key) {
        case InputKeyUp:
            code = HID_KEYBOARD_UP_ARROW;
            break;
        case InputKeyDown:
            code = HID_KEYBOARD_DOWN_ARROW;
            break;
        case InputKeyLeft:
            code = HID_KEYBOARD_LEFT_ARROW;
            break;
        case InputKeyRight:
            code = HID_KEYBOARD_RIGHT_ARROW;
            break;
        default:
            break;
        }
    } else if(event->key == InputKeyOk && event->type == InputTypeShort) {
        code = HID_KEYBOARD_RETURN;
    } else if(event->key == InputKeyBack && event->type == InputTypeShort) {
        code = HID_KEYBOARD_ESCAPE;
    }

    if(code && remote_pulse(app, code, consumer)) {
        furi_mutex_acquire(app->lock, FuriWaitForever);
        app->screen.highlight = true;
        app->screen.last_key = event->key;
        app->highlight_until = furi_get_tick() + furi_ms_to_ticks(160);
        furi_mutex_release(app->lock);
        view_port_update(app->view_port);
    }
    return true;
}

int32_t apple_tv_remote_app(void* context) {
    UNUSED(context);
    Remote* app = malloc(sizeof(Remote));
    memset(app, 0, sizeof(Remote));
    app->input = furi_message_queue_alloc(32, sizeof(InputEvent));
    app->lock = furi_mutex_alloc(FuriMutexTypeNormal);
    app->view_port = view_port_alloc();
    view_port_draw_callback_set(app->view_port, remote_draw, app);
    view_port_input_callback_set(app->view_port, remote_input, app);
    app->gui = furi_record_open(RECORD_GUI);
    app->bt = furi_record_open(RECORD_BT);
    gui_add_view_port(app->gui, app->view_port, GuiLayerFullscreen);

    bt_disconnect(app->bt);
    furi_delay_ms(200);
    Storage* storage = furi_record_open(RECORD_STORAGE);
    storage_common_mkdir(storage, REMOTE_BOND_DIR);
    furi_record_close(RECORD_STORAGE);
    bt_keys_storage_set_storage_path(app->bt, REMOTE_BOND_PATH);
    app->profile = bt_profile_start(app->bt, ble_profile_hid, NULL);
    if(app->profile) {
        bt_set_status_changed_callback(app->bt, remote_bt_status, app);
        furi_hal_bt_start_advertising();
    } else {
        furi_mutex_acquire(app->lock, FuriWaitForever);
        app->screen.failed = true;
        furi_mutex_release(app->lock);
        view_port_update(app->view_port);
    }

    InputEvent event;
    bool running = true;
    while(running) {
        if(furi_message_queue_get(app->input, &event, furi_ms_to_ticks(50)) == FuriStatusOk) {
            running = remote_handle_input(app, &event);
        }
        furi_mutex_acquire(app->lock, FuriWaitForever);
        bool clear = app->screen.highlight &&
                     (int32_t)(furi_get_tick() - app->highlight_until) >= 0;
        if(clear) app->screen.highlight = false;
        furi_mutex_release(app->lock);
        if(clear) view_port_update(app->view_port);
    }

    bt_set_status_changed_callback(app->bt, NULL, NULL);
    if(app->profile) {
        ble_profile_hid_kb_release_all(app->profile);
        ble_profile_hid_consumer_key_release_all(app->profile);
    }
    bt_disconnect(app->bt);
    furi_delay_ms(200);
    bt_keys_storage_set_default_path(app->bt);
    bool restored = bt_profile_restore_default(app->bt);
    if(!restored) FURI_LOG_E("AppleTV", "Could not restore default Bluetooth profile");

    view_port_enabled_set(app->view_port, false);
    gui_remove_view_port(app->gui, app->view_port);
    view_port_free(app->view_port);
    furi_record_close(RECORD_BT);
    furi_record_close(RECORD_GUI);
    furi_message_queue_free(app->input);
    furi_mutex_free(app->lock);
    free(app);
    return 0;
}
