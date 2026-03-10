import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import threading

class LinuxBonjourDBusService(dbus.service.Object):
    def __init__(self):
        bus_name = dbus.service.BusName("org.linuxbonjour.FaceService", bus=dbus.SystemBus())
        dbus.service.Object.__init__(self, bus_name, "/org/linuxbonjour/FaceService")

    @dbus.service.signal("org.linuxbonjour.FaceService", signature='s')
    def FaceVerified(self, username):
        """Emitted when a user is successfully verified."""
        pass

    @dbus.service.signal("org.linuxbonjour.FaceService", signature='s')
    def FaceDenied(self, username):
        """Emitted when access is denied."""
        pass

    @dbus.service.signal("org.linuxbonjour.FaceService", signature='s')
    def ScanningStarted(self, username):
        """Emitted when a biometric scan begins."""
        pass

    @dbus.service.signal("org.linuxbonjour.FaceService", signature='ss')
    def AuthRequested(self, username, service):
        """Emitted when user interaction is required before scanning."""
        pass

    @dbus.service.signal("org.linuxbonjour.FaceService", signature='ss')
    def AuthRequested(self, username, service):
        """Emitted when user interaction is required before scanning."""
        pass

class DBusManager:
    def __init__(self):
        self.service = None
        self.thread = None

    def start(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.service = LinuxBonjourDBusService()
            loop = GLib.MainLoop()
            loop.run()
        except Exception as e:
            print(f"DBus Service Error: {e}")

    def emit_verified(self, username):
        if self.service:
            GLib.idle_add(self.service.FaceVerified, username)

    def emit_denied(self, username):
        if self.service:
            GLib.idle_add(self.service.FaceDenied, username)

    def emit_scanning(self, username):
        if self.service:
            GLib.idle_add(self.service.ScanningStarted, username)

    def emit_auth_requested(self, username, service):
        if self.service:
            GLib.idle_add(self.service.AuthRequested, username, service)
