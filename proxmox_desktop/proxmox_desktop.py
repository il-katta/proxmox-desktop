#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Path: proxmox-desktop.py
# https://monroeclinton.com/build-your-own-window-manager/
# https://docs.qtile.org/en/0.10.5/_modules/libqtile/manager.html

import io
import logging
import os
import pprint
from signal import Signals
import subprocess
import threading
import time
from pathlib import Path
from threading import Thread
from typing import Any, List, Optional

import Xlib.display
import Xlib.ext.dpms
import Xlib.ext.randr
import Xlib.xobject.drawable
import xcffib
import xcffib.xproto
from systemd.journal import JournalHandler

from proxmox_desktop.proxmox_viewer import ProxmoxViewer

pp = pprint.PrettyPrinter(indent=4)

_NET_WM_STATE_REMOVE = 0
_NET_WM_STATE_ADD = 1
_NET_WM_STATE_TOGGLE = 2


class MWM(threading.Thread):
    _screen_rotation: int

    _display: Optional[str]

    _vt: int

    _processes: List[subprocess.Popen] = []

    display: Optional[Xlib.display.Display]

    conn: Optional[xcffib.Connection]

    setup: Optional[xcffib.xproto.Setup]

    _main_proc: Optional[Thread] = None

    _vmid: int

    _windows: set[int]

    _delta_y = 0

    _border = -3

    def __init__(
            self,
            vmid: int,
            screen_rotation: int = Xlib.ext.randr.Rotate_0,
            display: Optional[str] = None,
            vt: int = 8,
            log_level: int = logging.DEBUG,
            log_file: str = "proxmox-desktop.log",
            no_x: bool = False,
            proxmox_host: Optional[str] = None,
            proxmox_backend: Optional[str] = "local",
            remote_viewer_path: str = '/usr/bin/remote-viewer',
            proxmox_user: Optional[str] = None,
            proxmox_password: Optional[str] = None,
            proxmox_verify_ssl: Optional[bool] = None,
            **kwargs,
    ):
        super().__init__()
        self.main_window = None
        self.root_gc = None
        self.screen = None
        self.gc = None
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                JournalHandler(SYSLOG_IDENTIFIER='proxmox-desktop'),
                logging.FileHandler(filename=log_file, encoding=io.text_encoding('utf-8'), mode='w'),
                logging.StreamHandler()
            ],
            force=True
        )
        self._screen_rotation = screen_rotation
        self._display = display
        self._vt = vt
        self._no_x = no_x
        self._windows = set()

        proxmox_kwargs = {}
        for k, v in kwargs.items():
            if k.startswith('proxmox_'):
                proxmox_kwargs[k[8:]] = v
        self._vmid = vmid
        self._proxmox = ProxmoxViewer(
            host=proxmox_host,
            user=proxmox_user,
            password=proxmox_password,
            verify_ssl=proxmox_verify_ssl,
            backend=proxmox_backend,
            remote_viewer_path=remote_viewer_path,
            **proxmox_kwargs
        )

    def init(self):
        logging.info("connecting to X server")
        if self._display:
            os.putenv("DISPLAY", self._display)
        logging.info("connecting to X server")
        self.conn = xcffib.connect(display=self._display)
        self._NET_WM_STATE = self.conn.core.InternAtom(False, len("_NET_WM_STATE"), "_NET_WM_STATE").reply().atom
        self._NET_WM_STATE_MAXIMIZED_VERT = self.conn.core.InternAtom(True, len("_NET_WM_STATE_MAXIMIZED_VERT"),
                                                                      "_NET_WM_STATE_MAXIMIZED_VERT").reply().atom
        self._NET_WM_STATE_MAXIMIZED_VERT = self.conn.core.InternAtom(True, len("_NET_WM_STATE_MAXIMIZED_HORZ"),
                                                                      "_NET_WM_STATE_MAXIMIZED_HORZ").reply().atom
        self.setup = self.conn.get_setup()
        logging.info(f"connection: {pp.pformat(self.conn)}")
        for i, s in enumerate(self.conn.get_screen_pointers()):
            logging.info(
                f"get_screen_pointers {i} - root {s.root} width_in_pixels {s.width_in_pixels} height_in_pixels {s.height_in_pixels}"
            )
        # for i, s in enumerate(self.setup.roots):
        #    logging.info(
        #        f"setup.roots {i}: root {s.root} width_in_pixels {s.width_in_pixels} height_in_pixels {s.height_in_pixels}"
        #    )

        self.display: Xlib.display.Display = Xlib.display.Display(self._display)
        logging.info(
            f"display: {pp.pformat(self.display)} {self.display.get_display_name()}"
        )
        # for i, s in enumerate(self.display.display.info.roots):
        #    logging.info(
        #        f"display.display.info.roots {i}: root {s.root} width_in_pixels {s.width_in_pixels} height_in_pixels {s.height_in_pixels}"
        #    )
        self.screen = self.conn.get_screen_pointers()[0]
        # self.screen = self.display.screen()
        logging.info(f"screen: {pp.pformat(self.screen)}")
        logging.info(
            f"screen size: {self.screen.width_in_pixels}, {self.screen.height_in_pixels}"
        )

        if not self._no_x:
            logging.info("running X event loop")
            # Tell X server which events we wish to receive for the root window.

            cookie = self.conn.core.ChangeWindowAttributesChecked(
                self.screen.root,
                xcffib.xproto.CW.EventMask,  # Window attribute to set which events we want
                [
                    # We want to receive any substructure changes. This includes window
                    # creation/deletion, resizes, etc.
                    xcffib.xproto.EventMask.SubstructureNotify |
                    # We want X server to redirect children substructure notifications to the
                    # root window. Our window manager then processes these notifications.
                    # Only a single X client can use SubstructureRedirect at a time.
                    # This means if the request to changes attributes fails, another window manager
                    # is probably running.
                    xcffib.xproto.EventMask.SubstructureRedirect |
                    xcffib.xproto.EventMask.Exposure |
                    xcffib.xproto.EventMask.PropertyChange |
                    xcffib.xproto.EventMask.StructureNotify |
                    xcffib.xproto.EventMask.SubstructureNotify |
                    xcffib.xproto.EventMask.FocusChange |
                    xcffib.xproto.EventMask.EnterWindow |
                    xcffib.xproto.EventMask.LeaveWindow |
                    xcffib.xproto.EventMask.ButtonPress |
                    xcffib.xproto.EventMask.ButtonRelease |
                    xcffib.xproto.EventMask.KeyPress |
                    xcffib.xproto.EventMask.KeyRelease |
                    xcffib.xproto.EventMask.PointerMotion
                ]
            )
            cookie.check()

            screen = self.display.screen()
            self.root_gc = screen.root.create_gc(
                foreground=screen.black_pixel,
                background=screen.white_pixel,
            )

            self.main_window = screen.root.create_window(
                x=0, y=0,
                width=self.screen.width_in_pixels,
                height=self.screen.height_in_pixels,
                border_width=0,
                depth=screen.root_depth,
                background_pixel=screen.white_pixel,
                event_mask=Xlib.X.ExposureMask | Xlib.X.KeyPressMask,
            )
            self.gc = self.main_window.create_gc(
                foreground=screen.black_pixel,
                background=screen.white_pixel,
            )
            self.main_window.map()

    def run(self):
        try:
            self._run()
        except Exception as e:
            logging.exception(e)

    def _run(self):
        try:
            self.chvt()
        except Exception as e:
            logging.error("failed to change vt")
            logging.exception(e)
        if not self._no_x:
            self.run_xorg()
            # TODO: replace with a function that waits for the X server to start
            time.sleep(3)
        self.init()

        self._write_status("initialization complete. starting apps...")

        logging.info("running apps")
        self.run_apps()

        logging.info("waiting main process")
        self._write_status("waiting main process...")
        while self._main_proc is None:
            time.sleep(1)

        self._write_status("connecting ...")
        logging.info("processing events")
        terminate_event = threading.Event()
        display_loop = Thread(target=self._display_loop, args=[terminate_event])
        display_loop.start()
        while event := self.get_event():
            if isinstance(self._main_proc, Thread) and not self._main_proc.is_alive():
                terminate_event.set()
                self._write_status("exiting...")
                logging.info("main process process is terminated")
                display_loop.join(5)
                self.display.close()
                break

            if isinstance(event, bool):
                continue

            try:
                if hasattr(event, 'window'):
                    logging.info(f"X event: {pp.pformat(event)} window: {event.window}")
                else:
                    logging.info(f"X event: {pp.pformat(event)}")
                if isinstance(event, xcffib.xproto.CreateNotifyEvent):
                    logging.info(f"X event: CreateNotifyEvent {event.window}")
                    self._handle_create_notify_event(event)
                    self.conn.flush()

                if isinstance(event, xcffib.xproto.ConfigureRequestEvent):
                    logging.info(f"X event: ConfigureRequestEvent")
                    self._handle_configure_request_event(event)
                    self.conn.flush()

                if isinstance(event, xcffib.xproto.MapRequestEvent):
                    logging.info(f"X event: MapRequestEvent")
                    self._handle_map_request_event(event)
                    self.conn.flush()

                if isinstance(event, xcffib.xproto.MappingNotifyEvent):
                    logging.info(f"X event: MappingNotifyEvent")
                    self._handle_mapping_notify_event(event)
                    self.conn.flush()

                if isinstance(event, xcffib.xproto.UnmapNotifyEvent):
                    logging.info(f"X event: UnmapNotifyEvent")
                    self._handle_unmap_notify_event(event)
                    self.conn.flush()

                if isinstance(event, xcffib.xproto.DestroyNotifyEvent):
                    logging.info(f"X event: DestroyNotifyEvent")
                    self._handle_destroy_notify_event(event)

                if isinstance(event, xcffib.xproto.LeaveNotifyEvent):
                    logging.info(f"X event: LeaveNotifyEvent {event.detail}")

                if isinstance(event, xcffib.xproto.KeyPressEvent):
                    logging.info(
                        f"X event: KeyPressEvent time: {event.time} root: {event.root} event: {event.event} child: {event.child} root_x: {event.root_x} root_y: {event.root_y} event_x: {event.event_x} event_y: {event.event_y} state: {event.state} keycode: {event.detail} same_screen: {event.same_screen}")

                if isinstance(event, xcffib.xproto.PropertyNotifyEvent):
                    logging.info(
                        f"X event: PropertyNotifyEvent window: {event.window} state: {event.state} atom: {event.atom} time: {event.time}"
                    )

                if isinstance(event, xcffib.xproto.ClientMessageEvent):
                    self._handle_client_message_event(event)

                if isinstance(event, xcffib.xproto.FocusInEvent):
                    logging.info(f"X event: FocusInEvent {event.mode}")

                if isinstance(event, xcffib.xproto.FocusOutEvent):
                    logging.info(f"X event: FocusOutEvent {event.mode}")

                if isinstance(event, xcffib.xproto.ButtonPressEvent):
                    logging.info(f"X event: ButtonPressEvent {event.detail}")

                if isinstance(event, xcffib.xproto.ButtonReleaseEvent):
                    logging.info(f"X event: ButtonReleaseEvent {event.detail}")

                if isinstance(event, xcffib.xproto.MotionNotifyEvent):
                    logging.info(f"X event: MotionNotifyEvent {event.detail}")

                # self.conn.flush()
            except Exception as e:
                logging.error(pp.pformat(e))
                logging.exception(e)

            try:
                self.conn.invalid()
            except:
                logging.warning("connection invalidated")
                break

    def _display_loop(self, terminate_event: threading.Event):
        while terminate_event.is_set() is False:
            e = self.display.next_event()
            logging.info(f"Xlib display event: {e}")
            if e.type == Xlib.X.Expose:
                self.main_window.fill_rectangle(gc=self.gc, x=20, y=20, width=10, height=10)
                self._write_status()

    _status = None

    def _write_status(self, msg: Optional[str] = None):
        if msg is not None:
            self._status = msg
        if self._status is None:
            self._status = "starting..."
        self.main_window.clear_area(0, 0, self.screen.width_in_pixels, self.screen.height_in_pixels)
        self.main_window.draw_text(
            gc=self.gc,
            x=int(self.screen.width_in_pixels / 2),
            y=int(self.screen.height_in_pixels / 2),
            text=self._status
        )
        self.display.flush()

    def run_process(self, process_name: str, args: List[str], restart=False) -> Thread:
        thread = Thread(target=self._runprocess, args=[process_name, args, restart])
        thread.start()
        return thread

    def _runprocess(self, process_name: str, args: List[str], restart=False):
        logging.info(f"exec '{process_name}': {args}")
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self._processes.append(process)
        with process.stdout:
            for line in iter(process.stdout.readline, b''):
                # logging.info(f"{process_name}: {line.decode('utf-8')}")
                logging.info(f"{process_name}: %r", line)
        exitcode = process.wait()
        logging.info(f"{process_name} exit code: {exitcode}")
        if restart:  # TODO: check stop signal (??)
            self._runprocess(process_name=process_name, args=args, restart=restart)

    def run_apps(self):
        # disabilita screensaver
        logging.info("disable screen saver")
        self.screen_saver_disable()

        # disable screen standby
        logging.info("disable screen standby")
        self.dpms_disable()
        # self.disable_screen_standby()
        self.configure_screensaver()

        logging.info("rotating screen")
        self.screen_rotate()

        # main app
        logging.info("start main app")
        self.run_viewer()

    def chvt(self):
        logging.info(f"changing vt to {self._vt}")
        self.run_process("chvt", ["chvt", str(self._vt)])

    def run_xorg(self):
        logging.info("starting Xorg")
        self.run_process(
            "Xorg",
            [
                "Xorg", self._display,
                "-nolisten", "tcp",
                "-keeptty",
                f"vt{self._vt}",
                # f"tty{self._vt}",
                "-verbose", "0",
                # "-once",
                "-logfile", "/dev/stdout",
            ]
        )

    def disable_screen_standby(self):
        self.run_process("xset", ["xset", "s", "off", "-dpms"])

    def run_viewer(self):
        if self._screen_rotation in [0, 2]:
            windows_size = f"{self.screen.height_in_pixels},{self.screen.width_in_pixels}"
        else:
            windows_size = f"{self.screen.width_in_pixels},{self.screen.height_in_pixels}"
        logging.info(f"windows size: {windows_size}")
        self._main_proc = Thread(
            target=self._proxmox.remote_viewer,
            args=[
                self._vmid,
                None,
                [
                    '--full-screen',
                    # '--spice-debug', '--debug',
                    '--kiosk', '--kiosk-quit=on-disconnect',
                    f'--display={self._display}',
                ],
                False
            ]
        )
        self._main_proc.start()

    def configure_screensaver(self):
        self.run_process("xset", ["xset", "s", "600"])
        # self.run_process("xss-lock", ["xss-lock", "--", "<command to execute as screensaver>"])

    def screen_rotate(self):
        self.screen_rotate_xrandr()

    def screen_rotate_xrandr(self):
        rotation = str(self._screen_rotation)
        self.run_process(
            "xrandr",
            ["xrandr", "--orientation", rotation, "--verbose"]
        )

    def screen_rotate_xlib(self):
        if self.display.has_extension('RANDR'):
            logging.debug("screen rotate - getting screen")
            screen = self.display.screen()
            logging.debug("screen rotate - getting info")
            info = screen.root.xrandr_get_screen_info()
            logging.debug(f"info {pp.pformat(info)}")
            logging.debug(
                f"screen rotate - xrandr_set_screen_config {info.size_id} {self._screen_rotation} {info.config_timestamp}"
            )
            screen.root.xrandr_set_screen_config(
                size_id=info.size_id,
                rotation=self._screen_rotation,
                config_timestamp=info.config_timestamp
            )

    def screen_saver_disable(self):
        screen_saver = self.display.get_screen_saver()
        self.display.set_screen_saver(
            timeout=0,
            interval=screen_saver.interval,
            prefer_blank=screen_saver.prefer_blanking,
            allow_exposures=screen_saver.allow_exposures
        )

    def dpms_disable(self):
        if not hasattr(self.display, 'dpms_capable'):
            logging.info("dpms not capable")
            return
        if self.display.dpms_capable():
            logging.info("dpms disable")
            self.display.dpms_disable()
            self.display.sync()

    def dpms_enable(self):
        if not hasattr(self.display, 'dpms_capable'):
            logging.info("dpms not capable")
            return
        if self.display.dpms_capable():
            logging.info("dpms enable")
            self.display.dpms_enable()
            self.display.sync()

    def display_off(self):
        if self.display.dpms_capable():
            self.dpms_enable()
            logging.info("screen off")
            self.display.dpms_force_level(Xlib.ext.dpms.DPMSModeOff)
            self.display.sync()

    def display_on(self):
        if self.display.dpms_capable():
            logging.info("screen on")
            self.display.dpms_force_level(Xlib.ext.dpms.DPMSModeOn)
            self.display.sync()
        self.dpms_disable()

    @property
    def _dim_width(self) -> int:
        if self._border < 0:
            return self.screen.width_in_pixels + (abs(self._border) * 2)
        return self.screen.width_in_pixels

    @property
    def _dim_x(self) -> int:
        if self._border < 0:
            return self._border
        return 0

    @property
    def _dim_height(self) -> int:
        if self._border < 0:
            return self.screen.height_in_pixels + (abs(self._border) * 2)
        return self.screen.height_in_pixels

    @property
    def _dim_y(self) -> int:
        if self._border > 0:
            return self._delta_y
        return self._border + self._delta_y

    @property
    def _dim_border(self):
        if self._border < 0:
            return 0
        return self._border

    def _handle_configure_request_event(self, event: xcffib.xproto.ConfigureRequestEvent):
        logging.info(f"_handle_configure_request_event {pp.pformat(event)}")

        self.conn.core.ConfigureWindow(
            event.window,
            xcffib.xproto.ConfigWindow.X |
            xcffib.xproto.ConfigWindow.Y |
            xcffib.xproto.ConfigWindow.Width |
            xcffib.xproto.ConfigWindow.Height |
            xcffib.xproto.ConfigWindow.BorderWidth |
            xcffib.xproto.ConfigWindow.Sibling |
            xcffib.xproto.ConfigWindow.StackMode,
            [
                self._dim_x,
                self._dim_y,
                self._dim_width,
                self._dim_height,
                self._dim_border,
                # Siblings are windows that share the same parent. When configuring a window
                # you can specify a sibling window and a stack mode. For example if you
                # specify a sibling window and Above as the stack mode, the window
                # will appear above the sibling window specified.
                event.sibling,
                # Stacking order is where the window should appear.
                # For example above/below the sibling window above.
                event.stack_mode
            ]
        )
        logging.info(
            f"ConfigureRequest - window: {event.window} x: {event.x} y: {event.y} width: {event.width} height: {event.height} border_width: {event.border_width} sibling: {event.sibling} stack_mode: {event.stack_mode}"
        )

    def _handle_create_notify_event(self, event: xcffib.xproto.CreateNotifyEvent):
        logging.info(f"_handle_create_notify_event {pp.pformat(event)}")
        self.conn.core.MapWindow(event.window)
        self._windows.add(event.window)

    def _handle_destroy_notify_event(self, event: xcffib.xproto.DestroyNotifyEvent):
        logging.info(f"_handle_destroy_notify_event {pp.pformat(event)}")
        logging.info(
            f"DestroyNotify: event {event.event} window {event.window}"
        )
        if event.window in self._windows:
            self._windows.remove(event.window)

    def _handle_unmap_notify_event(self, event: xcffib.xproto.UnmapNotifyEvent):
        logging.info(f"_handle_unmap_notify_event {pp.pformat(event)}")
        logging.info(
            f"UnmapNotify: event {event.event} window {event.window} from_configure {event.from_configure}"
        )

    def _handle_mapping_notify_event(self, event: xcffib.xproto.MappingNotifyEvent):
        logging.info(f"_handle_mapping_notify_event {pp.pformat(event)}")
        logging.info(
            f"MappingNotify: request {event.request} first_keycode {event.first_keycode} count {event.count}"
        )

    def _handle_map_request_event(self, event: xcffib.xproto.MapRequestEvent):
        logging.info(f"_handle_map_request_event {pp.pformat(event)}")
        """
        When a window wants to map, meaning make itself visible, it send a MapRequestEvent that
        gets send to the window manager. Here we add it to our client list and finish by sending
        a MapWindow request to the server. This request tells the X server to make the window
        visible.
        :param event: MapRequestEvent to handle
        """

        # Get attributes associated with the window
        attributes = self.conn.core.GetWindowAttributes(
            event.window
        ).reply()

        # If the window has the override_redirect attribute set as true then the window manager
        # should not manage the window.
        if attributes.override_redirect:
            return

        # Send map window request to server, telling the server to make this window visible
        self.conn.core.MapWindow(event.window)

        # Resize the window to take up whole screen
        self.conn.core.ConfigureWindow(
            event.window,
            xcffib.xproto.ConfigWindow.X |
            xcffib.xproto.ConfigWindow.Y |
            xcffib.xproto.ConfigWindow.Width |
            xcffib.xproto.ConfigWindow.Height |
            xcffib.xproto.ConfigWindow.BorderWidth,
            [
                self._dim_x,
                self._dim_y,
                self._dim_width,
                self._dim_height,
                self._dim_border,
            ]
        )

    def _handle_client_message_event(self, event):
        if event.format == 32:
            data = event.data.data32
        if event.format == 16:
            data = event.data.data16
        if event.format == 8:
            data = event.data.data8

        logging.info(
            f"X event: ClientMessageEvent window: {event.window} format: {event.format} type: {event.type} data: {data}"
        )
        # check if the event is a _NET_WM_STATE event
        if event.type == self._NET_WM_STATE:
            # get window property _NET_WM_STATE
            current_state = self.conn.core.GetProperty(
                False,
                event.window,
                self._NET_WM_STATE,
                xcffib.xproto.Atom.ATOM,
                0,
                2 ** 32 - 1
            ).reply().value.to_atoms()
            current_state = set(current_state)
            logging.info(f"current state: {current_state}")
            action = data[0]
            for prop in (data[1], data[2]):
                if not prop:
                    continue
                if action == _NET_WM_STATE_REMOVE:
                    current_state.discard(prop)
                elif action == _NET_WM_STATE_ADD:
                    current_state.add(prop)
                elif action == _NET_WM_STATE_TOGGLE:
                    current_state ^= set([prop])

                # send
                self.conn.core.ChangeProperty(
                    xcffib.xproto.PropMode.Replace,
                    event.window,
                    self._NET_WM_STATE,
                    xcffib.xproto.Atom.ATOM,
                    32,
                    len(current_state),
                    list(current_state)
                )
                self.conn.flush()

        if False:  # event.type == self.??:
            logging.info("create window")
            new_id = self.conn.generate_id()
            r = self.conn.core.CreateWindow(
                self.screen.root_depth,
                new_id,
                event.window,
                0,
                0,
                1,
                1,
                0,
                xcffib.xproto.WindowClass.InputOutput,
                0,
                xcffib.xproto.CW.EventMask,
                [xcffib.xproto.EventMask.StructureNotify]
            )
            self.conn.core.MapWindow(new_id)
            self.conn.flush()
            self._windows.add(new_id)
            # reply
            reply_event = xcffib.xproto.ClientMessageEvent.synthetic(
                format=32,
                window=event.window,
                type=self._NET_WM_STATE,
                data=xcffib.xproto.ClientMessageData.synthetic(
                    [new_id, 0, 0, 0, 0],
                    "I" * 5
                ),
            )
            self.conn.core.SendEvent(
                False,
                event.window,
                xcffib.xproto.EventMask.NoEvent,
                reply_event
            )
            self.conn.flush()

    def get_event(self) -> Any | None | bool:
        time.sleep(1)
        try:
            return self.conn.wait_for_event()
        except xcffib.ConnectionException as ce:
            logging.warning("X connection error")
            logging.exception(ce)
            return False
        except xcffib.xproto.WindowError as e:
            logging.warning("X window error")
            self.conn.flush()
            logging.exception(e)
            return True
        except Exception as e:
            logging.exception(e)
            return True

    def _kill_processes(self):

        for process in self._processes:
            try:
                if process.returncode is not None:
                    continue
                logging.info(f"terminating {process.args}")
                process.terminate()
                if process.wait(30) is None:
                    logging.info(f"killing {process.args}")
                    os.kill(process.pid, Signals.SIGKILL)
            except Exception as e:
                logging.exception(e)

    def __del__(self):
        if self.display:
            try:
                self.display.close()
            except Exception:
                pass
        self._kill_processes()

    def __enter__(self) -> "MWM":
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.__del__()


def main():
    from proxmox_desktop.debugger import setup_debugger
    setup_debugger()
    import argparse
    import configparser

    class StoreLogLevel(argparse.Action):
        _nameToLevel = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'WARN': logging.WARNING,
            'ERROR': logging.ERROR,
            'FATAL': logging.FATAL,
            'CRITICAL': logging.CRITICAL,
            'NOTSET': logging.NOTSET,
        }

        def __init__(self,
                     option_strings,
                     dest,
                     default=None,
                     type=None,
                     choices=None,
                     required=False,
                     help=None,
                     metavar=None):
            super().__init__(
                option_strings,
                dest,
                default=list(self._nameToLevel.keys())[0],
                type=type,
                choices=self._nameToLevel.keys(),
                required=required,
                help=help,
                metavar=metavar
            )

        def __call__(self, parser, namespace, values, option_string=None):
            setattr(namespace, self.dest, self._nameToLevel.get(values))

    class StoreScreenRotation(argparse.Action):

        _screen_rotation_map = {
            'normal': 0,
            'right': 1,
            'inverted': 2,
            'left': 3,
            '0': 0,
            '90': 1,
            '180': 2,
            '270': 3,
        }

        def __init__(self,
                     option_strings,
                     dest,
                     default=None,
                     type=None,
                     choices=None,
                     required=False,
                     help=None,
                     metavar=None):
            super().__init__(
                option_strings, dest, default=list(self._screen_rotation_map.keys())[0], type=type,
                choices=self._screen_rotation_map.keys(),
                required=required, help=help, metavar=metavar
            )

        def __call__(self, parser, namespace, values, option_string=None):
            if isinstance(values, int) or values.isnumeric():
                values = str(values)
            setattr(namespace, self.dest, self._screen_rotation_map.get(values))

    # read configuration file
    parser = argparse.ArgumentParser(
        prog='WM',
        description='',
        epilog=''
    )
    parser.add_argument('-v', '--vmid', default=None, type=int)
    parser.add_argument('-r', '--screen-rotation', action=StoreScreenRotation, default=0)
    parser.add_argument('-d', '--display', default=":0")
    parser.add_argument('-t', '--vt', choices=range(1, 10), type=int, default=8)
    parser.add_argument('-l', '--log-level', action=StoreLogLevel)
    parser.add_argument('-f', '--log-file', default='./proxmox-desktop.log', type=Path)
    parser.add_argument('-nx', '--no-x', action='store_true', default=False)
    parser.add_argument('--proxmox-host', default=None)
    parser.add_argument('--proxmox-backend', default="local", choices=["local", "openssh", "https", "ssh_paramiko"])
    parser.add_argument('--remote-viewer-path', default='/usr/bin/remote-viewer')
    parser.add_argument('--proxmox-user', default=None)
    parser.add_argument('--proxmox-password', default=None)
    parser.add_argument('--proxmox-verify-ssl', type=bool, default=None)
    parser.add_argument('--config', default='/etc/proxmox-desktop/config.ini', type=Path)
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config)
    if 'proxmox' in config:
        for k, v in config['proxmox'].items():
            kk = f'proxmox_{k}'
            if kk in vars(args):
                setattr(args, kk, v)
    if 'main' in config:
        for k, v in config['main'].items():
            if k in vars(args):
                setattr(args, k, v)
    if args.vmid is None and args.vt is None:
        raise ValueError("vmid or vt is required")

    if args.vmid is None:
        if 'vm' in config:
            if f'tty{args.vt}' in config['vm']:
                args.vmid = config['vm'].getint(f'tty{args.vt}')
            else:
                raise ValueError(f"no configuration for tty{args.vt} in [vm] section")
    try:
        with MWM(**vars(args)) as wm:
            wm.start()
            wm.join()
    except Exception as e:
        logging.exception(e)


if __name__ == '__main__':
    main()
