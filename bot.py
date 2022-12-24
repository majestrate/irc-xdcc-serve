#!/usr/bin/env python3.9
#
# irc xdcc serve bot
#


from irc.client import SimpleIRCClient as IRC
from irc.client import ip_quad_to_numstr
import logging
import re
import struct
import sys
import traceback
import os

class DCC:

    def __init__(self, conn, file, size):
        self._dcc_timeout = 60
        self._dcc = conn
        self._dcc_counter = 0
        self.position = 0
        self.filesize = size
        self._file = file
        self._dcc.reactor.scheduler.execute_every(1, self._pump)

    def end(self):
        self._dcc.disconnect()
        self._file.close()

    def send(self):
        data = self._file.read(1024)
        self._dcc.send_bytes(data)
        self.position += len(data)
        self._dcc_counter = 0
    
    def seek(self, amount):
        self._file.seek(amount)

    def _pump(self):
        if self._dcc_counter >= self._dcc_timeout:
            self.end()
        else:
            self._dcc_counter += 1

class ServBot(IRC):
    
    
    def __init__(self, chan, root, addr,port):
        self._log = logging.getLogger('ServBot-%s' % chan)
        IRC.__init__(self)
        self._chan = str(chan)
        if not os.path.exists(root):
            os.mkdir(root)
        self._root = root
        self._sendq = []
        self._active_dcc = {}
        self._dcc = None
        self._file = None
        self._dcc_timeout = 0
        self.reactor.scheduler.execute_every(1, self._pump)
        self._filesize = -1
        self.prefix = '\\'
        self._dcc_addr = addr
        self.port = port

    def on_ctcp(self, c, ev):
        self._log.info("got ctcp from {}".format(ev.source))
        
    def _pump(self):
        if self.connection.is_connected():
            if len(self._sendq) > 0 and self._dcc is None:

                nick, file = self._sendq.pop()
                nick = nick.split('!')[0]
                self._filesize = os.path.getsize(file)
                self._log.info('sendfile: %s %s' % (nick, file))
                self._dcc = self.dcc('raw').listen(('',self.port))#self.dcc_listen('raw')
                self._file = open(file, 'rb')
                print(self._dcc_addr)
                print(self.port)
                print (dir(self._dcc))
                self.connection.ctcp('DCC', nick, 'SEND %s %s %d %d' % (os.path.basename(file), 
                                                                        ip_quad_to_numstr(self._dcc_addr), 
                                                                        self.port,
                                                                        self._filesize))
            if self._dcc_timeout >= 60:
                self._dcc = None
                self._dcc_timeout = 0
            if self._dcc is not None:
                self._dcc_timeout += 1
    
    def on_nicknameinuse(self, conn, event):
        conn.nick(conn.get_nickname()+'_')

    def on_dcc_connect(self, conn, event):
        if self._dcc is None:
            self._log.info('dcc connect too late')

        dcc = DCC(conn, self._file, self._filesize)
        self._active_dcc[conn] = dcc
        self._dcc = None
        self._log.info('dcc connect')
        dcc.send()

    def on_dcc_disconnect(self, conn, event):
        if conn in self._active_dcc:
            dcc = self._active_dcc[conn]
            dcc.end()
            self._active_dcc.pop(conn)
            self._log.info('dcc disconnect')
                  
    def on_dccmsg(self, conn, event):
        dcc = self._active_dcc[conn]
        acked = struct.unpack('!I', event.arguments[0])
        if acked == dcc.filesize:
            dcc.end()
            self._active_dcc.pop(conn)
        else:
            if dcc.position == 0 and acked > 0:
                dcc.seek(acked)
            dcc.send()

    def on_welcome(self, conn, event):
        self._log.info('connected')
        self.connection.join(self._chan)

    def on_disconnect(self, conn, event):
        self._log.info('disconnected')
        conn.reconnect()

    def on_privmsg(self, conn, event):
        msg = ''.join(event.arguments)
        if msg.startswith(self.prefix):
            args = msg.split()
            cmd = args[0][1:]
            args = args[1:]
            print(cmd)
            result = self._do_cmd(event.source, cmd, args)
            for line in result:
                conn.privmsg(event.source.nick, line)

    def _do_cmd(self,nick, cmd, args):
        _cmd = 'cmd_' + cmd
        if hasattr(self, _cmd):
            try:
                self._log.info(_cmd)
                return getattr(self, _cmd)(nick, args)
            except Exception as e:
                return ['error: %s' % e]
        else:
            return ['no such command: ' + cmd]


    def cmd_ping(self,nick, args):
        return ['pong']

    def _walk_find(self, check):
        found = []
        for root, dirs, files in os.walk(self._root):
            for file in files:
                if check(file):
                    found.append(os.path.join(root, file))
        ret = [ '%d matches' % len(found) ]
        
        for match in found[:5]:
            size = os.path.getsize(match)
            ret.append(match.replace(self._root, "") + ' - size: %dB' % size)
        return ret

    def _do_dcc(self ,nick, file):
        self._sendq.append((nick, file))
        
    def cmd_help(self, nick, args):
        return ['use {}regex , {}find and {}get'.format(self.prefix, self.prefix, self.prefix), 'make sure to /quote dccallow +xdccbot']

    def cmd_get(self, nick, args):
        file = ' '.join(args)
        if '..' in file:
            return ['invalid file name']
        if file[0] == '/':
            file = file[1:]
        file = os.path.join(self._root, file)
        print (file)
        if os.path.exists(file):
            self._do_dcc(nick, file)
            return ['your request has been queued']
        else:
            return ['no such file']
    
    def cmd_find(self, nick, args):
        search = ' '.join(args)
        self._log.info('checking %s for %s' % ( self._root, search))
        def check(file):
            return search in file
        return self._walk_find(check)

    def cmd_regex(self, nick, args):
        self._log.info('checking %s for regexp %s' % (self._root, args[0]))
        r = re.compile(args[0])
        def check(file):
            return r.match(file) is not None
        return self._walk_find(check)

def main():
    log = logging.getLogger('main')
    
    def fatal(msg):
        log.error(msg)
        sys.exit(1)

    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--server', type=str, required=True)
    ap.add_argument('--address', type=str, required=True)
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--chan', type=str, required=True)
    ap.add_argument('--botname', type=str, required=True)
    ap.add_argument('--debug', action='store_const', const=True, default=False)
    ap.add_argument('--root', type=str, required=True)

    args = ap.parse_args()
    if args.debug:
        lvl = logging.DEBUG
    else:
        lvl = logging.INFO

    logging.basicConfig(level=lvl)
    
    host, port = None, None
    serv = args.server.split(':')
    if len(serv) == 2:
        try:
            host, port = serv[0], int(serv[1])
        except:
            fatal('bad port number: %s' % serv[1])
    elif len(serv) == 1:
        host, port = serv[0], 6667
    else:
        fatal('incorrect server format')

    log.info('serving files in %s' % args.root)
    bot = ServBot(args.chan, args.root, args.address,args.port)
    
    while True:
        try:
            log.info('connecting to %s:%d' % (host, port))
            bot.connect(host, port, args.botname)
        except Exception as e:
            fatal(str(e))
            
        log.info('starting')
        try:
            bot.start();
        except Exception as e:
            bot.connection.disconnect('bai')
            fatal(traceback.format_exc())


if __name__ == '__main__':
    main()
