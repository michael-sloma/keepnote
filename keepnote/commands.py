"""

    KeepNote
    Command processing for KeepNote

"""

#
#  KeepNote
#  Copyright (c) 2008-2009 Matt Rasmussen
#  Author: Matt Rasmussen <rasmus@mit.edu>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301, USA.
#

import errno, os, random, socket, sys, thread

import keepnote


KEEPNOTE_HEADER = "keepnote\n"

# TODO: ensure commands are executed in order, but don't allow malicious
# process to DOS main process


def get_lock_file():
    lockfile = keepnote.get_user_lock_file()
    aquire = False

    while True:
        try:
            fd = os.open(lockfile, os.O_CREAT|os.O_EXCL|os.O_RDWR, 0600)
            aquire = True
            break

        except OSError, e:
            if e.errno != errno.EEXIST:
                # unknown error, re-raise
                raise

            try:
                fd = os.open(lockfile, os.O_RDONLY)
                aquire = False
                break

            except OSError, e:
                if e.errno != errno.ENOENT:
                    # unknown error, re-raise
                    raise
            

    return aquire, fd
    

def open_socket(start_port=4000, end_port=10000, tries=10):
    s = socket.socket(socket.AF_INET)

    for i in range(tries):
        port = random.randint(start_port, end_port)
        try:
            s.bind(("localhost", port))
            s.listen(1)
            break
        except socket.error:
            port = None

    if port is None:
        s.close()
        s = None

    # print "open port", port

    return s, port
    
def process_connection(conn, addr, passwd, execfunc):
    """Process a connection"""

    try:
        #print "accept", addr
        connfile = conn.makefile("rw")
        #print "writing..."
        connfile.write(KEEPNOTE_HEADER)
        connfile.flush()
        #print "reading..."
        passwd2 = connfile.readline().rstrip("\n")
        command = connfile.readline()

        # ensure password matches
        if passwd2 != passwd:
            # password failed, close connection
            conn.close()
            return
        
        # TODO: parse command
        execfunc(parse_command(command))

        connfile.close()
        conn.close()

    except socket.error, e:
        print >>sys.stderr, e, ": error with connection"
        conn.close()


def listen_commands(sock, passwd, execfunc):
    """Listen for new connections and process their commands"""

    while True:
        try:
            conn, addr = sock.accept()
        except socket.error:
            continue

        thread.start_new_thread(process_connection, 
                                (conn, addr, passwd, execfunc))


def write_lock_file(fd, port, passwd):
    os.write(fd, "%d:%s" % (port, passwd))


def read_lock_file(fd):
    text = os.read(fd, 1000)
    port, passwd = text.split(":")
    port = int(port)
    return port, passwd


def make_passwd():
    """Generate a random password"""
    return str(random.randint(0, 1000000))


def unescape(text):
    
    text2 = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            if text[i+1] == "n":
                # newline
                text2.append("\n")
            else:
                # literal
                text2.append(text[i+1])
            i += 1
        else:
            text2.append(text[i])
            
        i += 1
        
    return "".join(text2)

def escape(text):
    
    text2 = []
    for c in text:
        if c == "\n":
            text2.append("\\n")
        elif c == " ":
            text2.append("\\ ")
        elif c == "\\":
            text2.append("\\\\")
        else:
            text2.append(c)
    
    return "".join(text2)


def parse_command(text):
    return [unescape(x) for x in text.split(" ")]

def format_command(argv):
    return " ".join(escape(x) for x in argv)



class CommandExecutor (object):

    def __init__(self):
        self._execfunc = None
        self._app = None


    def set_app(self, app):
        self._app = app


    def setup(self, execfunc):        

        tries = 2

        for i in range(tries):
            aquire, fd = get_lock_file()


            if aquire:
                # open socket and record port number in lock file
                passwd = make_passwd()
                sock, port = open_socket()
                if port is None:
                    raise Exception("Could not open socket")
                write_lock_file(fd, port, passwd)

                self._execfunc = execfunc

                # start listening to socket for remote commands
                thread.start_new_thread(listen_commands, (sock, passwd, 
                                                          self.execute))

                self._execfunc = execfunc
                return True

            else:
                # connect to main process through socket
                try:
                    port, passwd = read_lock_file(fd)
                    os.close(fd)
                    fd = None

                    # use port number to connect
                    s = socket.socket(socket.AF_INET)
                    s.connect(("localhost", port))
                    connfile = s.makefile()
                    
                    # ensure header matches
                    header = connfile.readline()
                    assert header == KEEPNOTE_HEADER

                    # send password
                    connfile.write("%s\n" % passwd)

                    def execute(app, argv):
                        # send command
                        # TODO: format correctly
                        connfile.write(format_command(argv))

                        connfile.close()
                        s.close()
                    self._execfunc = execute

                    return False

                except Exception, e:
                    # lockfile does not contain proper port number
                    # remove lock file and attempt to acquire again
                    if fd:
                        os.close(fd)
                    os.remove(keepnote.get_user_lock_file())

        raise Exception("cannot get lock")
    
    
    def execute(self, argv):
        self._execfunc(self._app, argv)


def get_command_executor(execfunc):
    cmd_exec = CommandExecutor()
    main_proc = cmd_exec.setup(execfunc)
    return main_proc, cmd_exec

















'''
# dbus
try:
    import dbus
    import dbus.bus
    import dbus.service
    import dbus.mainloop.glib
    
except ImportError:
    dbus = None


APP_NAME = "org.ods.rasm.KeepNote"



class SimpleCommandExecutor (object):
    def __init__(self, exec_func):
        self.app = None
        self.exec_func = exec_func

    def set_app(self, app):
        self.app = app

    def execute(self, argv):
        if self.app:
            self.exec_func(self.app, argv)


if dbus:
    class CommandExecutor (dbus.service.Object):
        def __init__(self, bus, path, name, exec_func):
            dbus.service.Object.__init__(self, bus, path, name)
            self.app = None
            self.exec_func = exec_func

        def set_app(self, app):
            self.app = app

        @dbus.service.method(APP_NAME, in_signature='as', out_signature='')
        def execute(self, argv):
            # send command to app

            if self.app:
                self.exec_func(self.app, argv)



def get_command_executor(listen, exec_func):
    
    # setup dbus
    if not dbus or not listen:
        return True, SimpleCommandExecutor(exec_func)

    # setup glib as main loop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    # get bus session
    bus = dbus.SessionBus()

    # test to see if KeepNote is already running
    if bus.request_name(APP_NAME, dbus.bus.NAME_FLAG_DO_NOT_QUEUE) != \
       dbus.bus.REQUEST_NAME_REPLY_EXISTS:
        return True, CommandExecutor(bus, '/', APP_NAME, exec_func)
    else:
        obj = bus.get_object(APP_NAME, "/")
        ce = dbus.Interface(obj, APP_NAME)
        return False, ce


'''
