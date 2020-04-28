#!/usr/bin/env python2
# -*- coding: utf-8 -*-


"""Build tool that finds dependencies automatically for any language.

fabricate is a build tool that finds dependencies automatically for any
language. It's small and just works. No hidden stuff behind your back. It was
inspired by Bill McCloskey's make replacement, memoize, but fabricate works on
Windows as well as Linux.

Read more about how to use it and how it works on the project page:
    http://code.google.com/p/fabricate/

Like memoize, fabricate is released under a "New BSD license". fabricate is
copyright (c) 2009 Brush Technology. Full text of the license is here:
    http://code.google.com/p/fabricate/wiki/License

To get help on fabricate functions:
    from fabricate import *
    help(function)

"""

from __future__ import with_statement
from __future__ import division

# fabricate version number
__version__ = '1.26'

# if version of .deps file has changed, we know to not use it
deps_version = 2

import atexit
import codecs
import glob
import optparse
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import threading # NB uses old camelCase names for backward compatibility
# multiprocessing module only exists on Python >= 2.6
try:
    import multiprocessing
except ImportError:
    class MultiprocessingModule(object):
        def __getattr__(self, name):
            raise NotImplementedError("multiprocessing module not available, can't do parallel builds")
    multiprocessing = MultiprocessingModule()

# so you can do "from fabricate import *" to simplify your build script
__all__ = ['setup', 'run', 'autoclean', 'main', 'shell', 'fabricate_version',
           'memoize', 'outofdate', 'parse_options', 'after',
           'ExecutionError', 'md5_hasher', 'mtime_hasher',
           'Runner', 'AlwaysRunner', 'TrackerRunner',
           'SmartRunner', 'FuseRunner', 'Builder']

import textwrap
import gc
import logging

logger = logging.getLogger("fabricate")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s/%(processName)s] %(message)s"))
logger.addHandler(handler)

import multiprocessing_logging
multiprocessing_logging.install_mp_handler()

__doc__ += "Exported functions are:\n" + '  ' + '\n  '.join(textwrap.wrap(', '.join(__all__), 80))



FAT_atime_resolution = 24*60*60     # resolution on FAT filesystems (seconds)
FAT_mtime_resolution = 2

# NTFS resolution is < 1 ms
# We assume this is considerably more than time to run a new process

NTFS_atime_resolution = 0.0002048   # resolution on NTFS filesystems (seconds)
NTFS_mtime_resolution = 0.0002048   #  is actually 0.1us but python's can be
                                    #  as low as 204.8us due to poor
                                    #  float precision when storing numbers
                                    #  as big as NTFS file times can be
                                    #  (float has 52-bit precision and NTFS
                                    #  FILETIME has 63-bit precision, so
                                    #  we've lost 11 bits = 2048)

# So we can use md5func in old and new versions of Python without warnings
try:
    import hashlib
    md5func = hashlib.md5
except ImportError:
    import md5
    md5func = md5.new

# Use json, or pickle on older Python versions if simplejson not installed
try:
    import json
except ImportError:
    try:
        import simplejson as json
    except ImportError:
        import cPickle
        # needed to ignore the indent= argument for pickle's dump()
        class PickleJson:
            def load(self, f):
                return cPickle.load(f)
            def dump(self, obj, f, indent=None, sort_keys=None):
                return cPickle.dump(obj, f)
        json = PickleJson()

HAS_FUSE=True
try:
#### FUSEPY#####
# Copyright (c) 2012 Terence Honles <terence@honles.com> (maintainer)
# Copyright (c) 2008 Giorgos Verigakis <verigak@gmail.com> (author)
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

    from ctypes import *
    from ctypes.util import find_library
    from errno import *
    from os import strerror
    from platform import machine, system
    from signal import signal, SIGINT, SIG_DFL
    from stat import S_IFDIR
    from traceback import print_exc

#    import logging
#    logger = multiprocessing.get_logger()
#    logger.setLevel(logging.ERROR)
#    handler = logging.StreamHandler()
#    handler.setFormatter(logging.Formatter("[%(levelname)s/%(processName)s] %(message)s"))
#    logger.addHandler(handler)
#    logging.root.addHandler(handler)
#    logging.root.setLevel(logging.INFO)

    try:
        from functools import partial
    except ImportError:
        # http://docs.python.org/library/functools.html#functools.partial
        def partial(func, *args, **keywords):
            def newfunc(*fargs, **fkeywords):
                newkeywords = keywords.copy()
                newkeywords.update(fkeywords)
                return func(*(args + fargs), **newkeywords)

            newfunc.func = func
            newfunc.args = args
            newfunc.keywords = keywords
            return newfunc

    try:
        basestring
    except NameError:
        basestring = str

    class c_timespec(Structure):
        _fields_ = [('tv_sec', c_long), ('tv_nsec', c_long)]

    class c_utimbuf(Structure):
        _fields_ = [('actime', c_timespec), ('modtime', c_timespec)]

    class c_stat(Structure):
        pass    # Platform dependent

    _system = system()
    _machine = machine()

    if _system == 'Darwin':
        _libiconv = CDLL(find_library('iconv'), RTLD_GLOBAL) # libfuse dependency
        _libfuse_path = (find_library('fuse4x') or find_library('osxfuse') or
                        find_library('fuse'))
    else:
        _libfuse_path = find_library('fuse')

    if not _libfuse_path:
        raise EnvironmentError('Unable to find libfuse')
    else:
        _libfuse = CDLL(_libfuse_path)

    if _system == 'Darwin' and hasattr(_libfuse, 'macfuse_version'):
        _system = 'Darwin-MacFuse'


    if _system in ('Darwin', 'Darwin-MacFuse', 'FreeBSD'):
        ENOTSUP = 45
        c_dev_t = c_int32
        c_fsblkcnt_t = c_ulong
        c_fsfilcnt_t = c_ulong
        c_gid_t = c_uint32
        c_mode_t = c_uint16
        c_off_t = c_int64
        c_pid_t = c_int32
        c_uid_t = c_uint32
        setxattr_t = CFUNCTYPE(c_int, c_char_p, c_char_p, POINTER(c_byte),
            c_size_t, c_int, c_uint32)
        getxattr_t = CFUNCTYPE(c_int, c_char_p, c_char_p, POINTER(c_byte),
            c_size_t, c_uint32)
        if _system == 'Darwin':
            c_stat._fields_ = [
                ('st_dev', c_dev_t),
                ('st_mode', c_mode_t),
                ('st_nlink', c_uint16),
                ('st_ino', c_uint64),
                ('st_uid', c_uid_t),
                ('st_gid', c_gid_t),
                ('st_rdev', c_dev_t),
                ('st_atimespec', c_timespec),
                ('st_mtimespec', c_timespec),
                ('st_ctimespec', c_timespec),
                ('st_birthtimespec', c_timespec),
                ('st_size', c_off_t),
                ('st_blocks', c_int64),
                ('st_blksize', c_int32),
                ('st_flags', c_int32),
                ('st_gen', c_int32),
                ('st_lspare', c_int32),
                ('st_qspare', c_int64)]
        else:
            c_stat._fields_ = [
                ('st_dev', c_dev_t),
                ('st_ino', c_uint32),
                ('st_mode', c_mode_t),
                ('st_nlink', c_uint16),
                ('st_uid', c_uid_t),
                ('st_gid', c_gid_t),
                ('st_rdev', c_dev_t),
                ('st_atimespec', c_timespec),
                ('st_mtimespec', c_timespec),
                ('st_ctimespec', c_timespec),
                ('st_size', c_off_t),
                ('st_blocks', c_int64),
                ('st_blksize', c_int32)]
    elif _system == 'Linux':
        ENOTSUP = 95
        c_dev_t = c_ulonglong
        c_fsblkcnt_t = c_ulonglong
        c_fsfilcnt_t = c_ulonglong
        c_gid_t = c_uint
        c_mode_t = c_uint
        c_off_t = c_longlong
        c_pid_t = c_int
        c_uid_t = c_uint
        setxattr_t = CFUNCTYPE(c_int, c_char_p, c_char_p, POINTER(c_byte),
                            c_size_t, c_int)

        getxattr_t = CFUNCTYPE(c_int, c_char_p, c_char_p, POINTER(c_byte),
                            c_size_t)

        if _machine == 'x86_64':
            c_stat._fields_ = [
                ('st_dev', c_dev_t),
                ('st_ino', c_ulong),
                ('st_nlink', c_ulong),
                ('st_mode', c_mode_t),
                ('st_uid', c_uid_t),
                ('st_gid', c_gid_t),
                ('__pad0', c_int),
                ('st_rdev', c_dev_t),
                ('st_size', c_off_t),
                ('st_blksize', c_long),
                ('st_blocks', c_long),
                ('st_atimespec', c_timespec),
                ('st_mtimespec', c_timespec),
                ('st_ctimespec', c_timespec)]
        elif _machine == 'ppc':
            c_stat._fields_ = [
                ('st_dev', c_dev_t),
                ('st_ino', c_ulonglong),
                ('st_mode', c_mode_t),
                ('st_nlink', c_uint),
                ('st_uid', c_uid_t),
                ('st_gid', c_gid_t),
                ('st_rdev', c_dev_t),
                ('__pad2', c_ushort),
                ('st_size', c_off_t),
                ('st_blksize', c_long),
                ('st_blocks', c_longlong),
                ('st_atimespec', c_timespec),
                ('st_mtimespec', c_timespec),
                ('st_ctimespec', c_timespec)]
        else:
            # i686, use as fallback for everything else
            c_stat._fields_ = [
                ('st_dev', c_dev_t),
                ('__pad1', c_ushort),
                ('__st_ino', c_ulong),
                ('st_mode', c_mode_t),
                ('st_nlink', c_uint),
                ('st_uid', c_uid_t),
                ('st_gid', c_gid_t),
                ('st_rdev', c_dev_t),
                ('__pad2', c_ushort),
                ('st_size', c_off_t),
                ('st_blksize', c_long),
                ('st_blocks', c_longlong),
                ('st_atimespec', c_timespec),
                ('st_mtimespec', c_timespec),
                ('st_ctimespec', c_timespec),
                ('st_ino', c_ulonglong)]
    else:
        raise NotImplementedError('%s is not supported.' % _system)


    class c_statvfs(Structure):
        _fields_ = [
            ('f_bsize', c_ulong),
            ('f_frsize', c_ulong),
            ('f_blocks', c_fsblkcnt_t),
            ('f_bfree', c_fsblkcnt_t),
            ('f_bavail', c_fsblkcnt_t),
            ('f_files', c_fsfilcnt_t),
            ('f_ffree', c_fsfilcnt_t),
            ('f_favail', c_fsfilcnt_t)]

    if _system == 'FreeBSD':
        c_fsblkcnt_t = c_uint64
        c_fsfilcnt_t = c_uint64
        setxattr_t = CFUNCTYPE(c_int, c_char_p, c_char_p, POINTER(c_byte),
                            c_size_t, c_int)

        getxattr_t = CFUNCTYPE(c_int, c_char_p, c_char_p, POINTER(c_byte),
                            c_size_t)

        class c_statvfs(Structure):
            _fields_ = [
                ('f_bavail', c_fsblkcnt_t),
                ('f_bfree', c_fsblkcnt_t),
                ('f_blocks', c_fsblkcnt_t),
                ('f_favail', c_fsfilcnt_t),
                ('f_ffree', c_fsfilcnt_t),
                ('f_files', c_fsfilcnt_t),
                ('f_bsize', c_ulong),
                ('f_flag', c_ulong),
                ('f_frsize', c_ulong)]

    class fuse_file_info(Structure):
        _fields_ = [
            ('flags', c_int),
            ('fh_old', c_ulong),
            ('writepage', c_int),
            ('direct_io', c_uint, 1),
            ('keep_cache', c_uint, 1),
            ('flush', c_uint, 1),
            ('padding', c_uint, 29),
            ('fh', c_uint64),
            ('lock_owner', c_uint64)]

    class fuse_context(Structure):
        _fields_ = [
            ('fuse', c_voidp),
            ('uid', c_uid_t),
            ('gid', c_gid_t),
            ('pid', c_pid_t),
            ('private_data', c_voidp)]

    _libfuse.fuse_get_context.restype = POINTER(fuse_context)


    class fuse_operations(Structure):
        _fields_ = [
            ('getattr', CFUNCTYPE(c_int, c_char_p, POINTER(c_stat))),
            ('readlink', CFUNCTYPE(c_int, c_char_p, POINTER(c_byte), c_size_t)),
            ('getdir', c_voidp),    # Deprecated, use readdir
            ('mknod', CFUNCTYPE(c_int, c_char_p, c_mode_t, c_dev_t)),
            ('mkdir', CFUNCTYPE(c_int, c_char_p, c_mode_t)),
            ('unlink', CFUNCTYPE(c_int, c_char_p)),
            ('rmdir', CFUNCTYPE(c_int, c_char_p)),
            ('symlink', CFUNCTYPE(c_int, c_char_p, c_char_p)),
            ('rename', CFUNCTYPE(c_int, c_char_p, c_char_p)),
            ('link', CFUNCTYPE(c_int, c_char_p, c_char_p)),
            ('chmod', CFUNCTYPE(c_int, c_char_p, c_mode_t)),
            ('chown', CFUNCTYPE(c_int, c_char_p, c_uid_t, c_gid_t)),
            ('truncate', CFUNCTYPE(c_int, c_char_p, c_off_t)),
            ('utime', c_voidp),     # Deprecated, use utimens
            ('open', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),

            ('read', CFUNCTYPE(c_int, c_char_p, POINTER(c_byte), c_size_t,
                            c_off_t, POINTER(fuse_file_info))),

            ('write', CFUNCTYPE(c_int, c_char_p, POINTER(c_byte), c_size_t,
                                c_off_t, POINTER(fuse_file_info))),

            ('statfs', CFUNCTYPE(c_int, c_char_p, POINTER(c_statvfs))),
            ('flush', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),
            ('release', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),
            ('fsync', CFUNCTYPE(c_int, c_char_p, c_int, POINTER(fuse_file_info))),
            ('setxattr', setxattr_t),
            ('getxattr', getxattr_t),
            ('listxattr', CFUNCTYPE(c_int, c_char_p, POINTER(c_byte), c_size_t)),
            ('removexattr', CFUNCTYPE(c_int, c_char_p, c_char_p)),
            ('opendir', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),

            ('readdir', CFUNCTYPE(c_int, c_char_p, c_voidp,
                                CFUNCTYPE(c_int, c_voidp, c_char_p,
                                            POINTER(c_stat), c_off_t),
                                c_off_t, POINTER(fuse_file_info))),

            ('releasedir', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info))),

            ('fsyncdir', CFUNCTYPE(c_int, c_char_p, c_int,
                                POINTER(fuse_file_info))),

            ('init', CFUNCTYPE(c_voidp, c_voidp)),
            ('destroy', CFUNCTYPE(c_voidp, c_voidp)),
            ('access', CFUNCTYPE(c_int, c_char_p, c_int)),

            ('create', CFUNCTYPE(c_int, c_char_p, c_mode_t,
                                POINTER(fuse_file_info))),

            ('ftruncate', CFUNCTYPE(c_int, c_char_p, c_off_t,
                                    POINTER(fuse_file_info))),

            ('fgetattr', CFUNCTYPE(c_int, c_char_p, POINTER(c_stat),
                                POINTER(fuse_file_info))),

            ('lock', CFUNCTYPE(c_int, c_char_p, POINTER(fuse_file_info),
                            c_int, c_voidp)),

            ('utimens', CFUNCTYPE(c_int, c_char_p, POINTER(c_utimbuf))),
            ('bmap', CFUNCTYPE(c_int, c_char_p, c_size_t, POINTER(c_ulonglong))),
        ]


    def time_of_timespec(ts):
        return ts.tv_sec + ts.tv_nsec / 10 ** 9

    def set_st_attrs(st, attrs):
        for key, val in attrs.items():
            if key in ('st_atime', 'st_mtime', 'st_ctime', 'st_birthtime'):
                timespec = getattr(st, key + 'spec')
                timespec.tv_sec = int(val)
                timespec.tv_nsec = int((val - timespec.tv_sec) * 10 ** 9)
            elif hasattr(st, key):
                setattr(st, key, val)


    def fuse_get_context():
        'Returns a (uid, gid, pid) tuple'

        ctxp = _libfuse.fuse_get_context()
        ctx = ctxp.contents
        return ctx.uid, ctx.gid, ctx.pid


    class FuseOSError(OSError):
        def __init__(self, errno):
            super(FuseOSError, self).__init__(errno, strerror(errno))


    class FUSE(object):
        '''
        This class is the lower level interface and should not be subclassed under
        normal use. Its methods are called by fuse.

        Assumes API version 2.6 or later.
        '''

        OPTIONS = (
            ('foreground', '-f'),
            ('debug', '-d'),
            ('nothreads', '-s'),
        )

        def __init__(self, operations, mountpoint, raw_fi=False, encoding='utf-8',
                    **kwargs):

            '''
            Setting raw_fi to True will cause FUSE to pass the fuse_file_info
            class as is to Operations, instead of just the fh field.

            This gives you access to direct_io, keep_cache, etc.
            '''

            self.operations = operations
            self.raw_fi = raw_fi
            self.encoding = encoding

            args = ['fuse']

            args.extend(flag for arg, flag in self.OPTIONS
                        if kwargs.pop(arg, False))

            kwargs.setdefault('fsname', operations.__class__.__name__)
            args.append('-o')
            args.append(','.join(self._normalize_fuse_options(**kwargs)))
            args.append(mountpoint)

            args = [arg.encode(encoding) for arg in args]
            argv = (c_char_p * len(args))(*args)

            fuse_ops = fuse_operations()
            for name, prototype in fuse_operations._fields_:
                if prototype != c_voidp and getattr(operations, name, None):
                    op = partial(self._wrapper, getattr(self, name))
                    setattr(fuse_ops, name, prototype(op))

            try:
                old_handler = signal(SIGINT, SIG_DFL)
            except ValueError:
                old_handler = SIG_DFL

            err = _libfuse.fuse_main_real(len(args), argv, pointer(fuse_ops),
                                        sizeof(fuse_ops), None)

            try:
                signal(SIGINT, old_handler)
            except ValueError:
                pass

            del self.operations     # Invoke the destructor
            if err:
                raise RuntimeError(err)

        @staticmethod
        def _normalize_fuse_options(**kargs):
            for key, value in kargs.items():
                if isinstance(value, bool):
                    if value is True: yield key
                else:
                    yield '%s=%s' % (key, value)

        @staticmethod
        def _wrapper(func, *args, **kwargs):
            'Decorator for the methods that follow'

            try:
                return func(*args, **kwargs) or 0
            except OSError, e:
                return -(e.errno or EFAULT)
            except:
                print_exc()
                return -EFAULT

        def getattr(self, path, buf):
            return self.fgetattr(path, buf, None)

        def readlink(self, path, buf, bufsize):
            ret = self.operations('readlink', path.decode(self.encoding)) \
                    .encode(self.encoding)

            # copies a string into the given buffer
            # (null terminated and truncated if necessary)
            data = create_string_buffer(ret[:bufsize - 1])
            memmove(buf, data, len(data))
            return 0

        def mknod(self, path, mode, dev):
            return self.operations('mknod', path.decode(self.encoding), mode, dev)

        def mkdir(self, path, mode):
            return self.operations('mkdir', path.decode(self.encoding), mode)

        def unlink(self, path):
            return self.operations('unlink', path.decode(self.encoding))

        def rmdir(self, path):
            return self.operations('rmdir', path.decode(self.encoding))

        def symlink(self, source, target):
            'creates a symlink `target -> source` (e.g. ln -s source target)'

            return self.operations('symlink', target.decode(self.encoding),
                                            source.decode(self.encoding))

        def rename(self, old, new):
            return self.operations('rename', old.decode(self.encoding),
                                            new.decode(self.encoding))

        def link(self, source, target):
            'creates a hard link `target -> source` (e.g. ln source target)'

            return self.operations('link', target.decode(self.encoding),
                                        source.decode(self.encoding))

        def chmod(self, path, mode):
            return self.operations('chmod', path.decode(self.encoding), mode)

        def chown(self, path, uid, gid):
            # Check if any of the arguments is a -1 that has overflowed
            if c_uid_t(uid + 1).value == 0:
                uid = -1
            if c_gid_t(gid + 1).value == 0:
                gid = -1

            return self.operations('chown', path.decode(self.encoding), uid, gid)

        def truncate(self, path, length):
            return self.operations('truncate', path.decode(self.encoding), length)

        def open(self, path, fip):
            fi = fip.contents
            if self.raw_fi:
                return self.operations('open', path.decode(self.encoding), fi)
            else:
                fi.fh = self.operations('open', path.decode(self.encoding),
                                                fi.flags)

                return 0

        def read(self, path, buf, size, offset, fip):
            if self.raw_fi:
                fh = fip.contents
            else:
                fh = fip.contents.fh

            ret = self.operations('read', path.decode(self.encoding), size,
                                        offset, fh)

            if not ret: return 0

            retsize = len(ret)
            assert retsize <= size, \
                'actual amount read %d greater than expected %d' % (retsize, size)

            data = create_string_buffer(ret, retsize)
            memmove(buf, ret, retsize)
            return retsize

        def write(self, path, buf, size, offset, fip):
            data = string_at(buf, size)

            if self.raw_fi:
                fh = fip.contents
            else:
                fh = fip.contents.fh

            return self.operations('write', path.decode(self.encoding), data,
                                            offset, fh)

        def statfs(self, path, buf):
            stv = buf.contents
            attrs = self.operations('statfs', path.decode(self.encoding))
            for key, val in attrs.items():
                if hasattr(stv, key):
                    setattr(stv, key, val)

            return 0

        def flush(self, path, fip):
            if self.raw_fi:
                fh = fip.contents
            else:
                fh = fip.contents.fh

            return self.operations('flush', path.decode(self.encoding), fh)

        def release(self, path, fip):
            if self.raw_fi:
                fh = fip.contents
            else:
                fh = fip.contents.fh

            return self.operations('release', path.decode(self.encoding), fh)

        def fsync(self, path, datasync, fip):
            if self.raw_fi:
                fh = fip.contents
            else:
                fh = fip.contents.fh

            return self.operations('fsync', path.decode(self.encoding), datasync,
                                            fh)

        def setxattr(self, path, name, value, size, options, *args):
            return self.operations('setxattr', path.decode(self.encoding),
                                name.decode(self.encoding),
                                string_at(value, size), options, *args)

        def getxattr(self, path, name, value, size, *args):
            ret = self.operations('getxattr', path.decode(self.encoding),
                                            name.decode(self.encoding), *args)

            retsize = len(ret)
            # allow size queries
            if not value: return retsize

            # do not truncate
            if retsize > size: return -ERANGE

            buf = create_string_buffer(ret, retsize)    # Does not add trailing 0
            memmove(value, buf, retsize)

            return retsize

        def listxattr(self, path, namebuf, size):
            attrs = self.operations('listxattr', path.decode(self.encoding)) or ''
            ret = '\x00'.join(attrs).encode(self.encoding) + '\x00'

            retsize = len(ret)
            # allow size queries
            if not namebuf: return retsize

            # do not truncate
            if retsize > size: return -ERANGE

            buf = create_string_buffer(ret, retsize)
            memmove(namebuf, buf, retsize)

            return retsize

        def removexattr(self, path, name):
            return self.operations('removexattr', path.decode(self.encoding),
                                                name.decode(self.encoding))

        def opendir(self, path, fip):
            # Ignore raw_fi
            fip.contents.fh = self.operations('opendir',
                                            path.decode(self.encoding))

            return 0

        def readdir(self, path, buf, filler, offset, fip):
            # Ignore raw_fi
            for item in self.operations('readdir', path.decode(self.encoding),
                                                fip.contents.fh):

                if isinstance(item, basestring):
                    name, st, offset = item, None, 0
                else:
                    name, attrs, offset = item
                    if attrs:
                        st = c_stat()
                        set_st_attrs(st, attrs)
                    else:
                        st = None

                if filler(buf, name.encode(self.encoding), st, offset) != 0:
                    break

            return 0

        def releasedir(self, path, fip):
            # Ignore raw_fi
            return self.operations('releasedir', path.decode(self.encoding),
                                                fip.contents.fh)

        def fsyncdir(self, path, datasync, fip):
            # Ignore raw_fi
            return self.operations('fsyncdir', path.decode(self.encoding),
                                            datasync, fip.contents.fh)

        def init(self, conn):
            return self.operations('init', '/')

        def destroy(self, private_data):
            return self.operations('destroy', '/')

        def access(self, path, amode):
            return self.operations('access', path.decode(self.encoding), amode)

        def create(self, path, mode, fip):
            fi = fip.contents
            path = path.decode(self.encoding)

            if self.raw_fi:
                return self.operations('create', path, mode, fi)
            else:
                fi.fh = self.operations('create', path, mode)
                return 0

        def ftruncate(self, path, length, fip):
            if self.raw_fi:
                fh = fip.contents
            else:
                fh = fip.contents.fh

            return self.operations('truncate', path.decode(self.encoding),
                                            length, fh)

        def fgetattr(self, path, buf, fip):
            memset(buf, 0, sizeof(c_stat))

            st = buf.contents
            if not fip:
                fh = fip
            elif self.raw_fi:
                fh = fip.contents
            else:
                fh = fip.contents.fh

            attrs = self.operations('getattr', path.decode(self.encoding), fh)
            set_st_attrs(st, attrs)
            return 0

        def lock(self, path, fip, cmd, lock):
            if self.raw_fi:
                fh = fip.contents
            else:
                fh = fip.contents.fh

            return self.operations('lock', path.decode(self.encoding), fh, cmd,
                                        lock)

        def utimens(self, path, buf):
            if buf:
                atime = time_of_timespec(buf.contents.actime)
                mtime = time_of_timespec(buf.contents.modtime)
                times = (atime, mtime)
            else:
                times = None

            return self.operations('utimens', path.decode(self.encoding), times)

        def bmap(self, path, blocksize, idx):
            return self.operations('bmap', path.decode(self.encoding), blocksize,
                                        idx)


    class Operations(object):
        '''
        This class should be subclassed and passed as an argument to FUSE on
        initialization. All operations should raise a FuseOSError exception on
        error.

        When in doubt of what an operation should do, check the FUSE header file
        or the corresponding system call man page.
        '''

        def __call__(self, op, *args):
            if not hasattr(self, op):
                raise FuseOSError(EFAULT)
            return getattr(self, op)(*args)

        def access(self, path, amode):
            return 0

        bmap = None

        def chmod(self, path, mode):
            raise FuseOSError(EROFS)

        def chown(self, path, uid, gid):
            raise FuseOSError(EROFS)

        def create(self, path, mode, fi=None):
            '''
            When raw_fi is False (default case), fi is None and create should
            return a numerical file handle.

            When raw_fi is True the file handle should be set directly by create
            and return 0.
            '''

            raise FuseOSError(EROFS)

        def destroy(self, path):
            'Called on filesystem destruction. Path is always /'

            pass

        def flush(self, path, fh):
            return 0

        def fsync(self, path, datasync, fh):
            return 0

        def fsyncdir(self, path, datasync, fh):
            return 0

        def getattr(self, path, fh=None):
            '''
            Returns a dictionary with keys identical to the stat C structure of
            stat(2).

            st_atime, st_mtime and st_ctime should be floats.

            NOTE: There is an incombatibility between Linux and Mac OS X
            concerning st_nlink of directories. Mac OS X counts all files inside
            the directory, while Linux counts only the subdirectories.
            '''

            if path != '/':
                raise FuseOSError(ENOENT)
            return dict(st_mode=(S_IFDIR | 0755), st_nlink=2)

        def getxattr(self, path, name, position=0):
            raise FuseOSError(ENOTSUP)

        def init(self, path):
            '''
            Called on filesystem initialization. (Path is always /)

            Use it instead of __init__ if you start threads on initialization.
            '''

            pass

        def link(self, target, source):
            'creates a hard link `target -> source` (e.g. ln source target)'

            raise FuseOSError(EROFS)

        def listxattr(self, path):
            return []

        lock = None

        def mkdir(self, path, mode):
            raise FuseOSError(EROFS)

        def mknod(self, path, mode, dev):
            raise FuseOSError(EROFS)

        def open(self, path, flags):
            '''
            When raw_fi is False (default case), open should return a numerical
            file handle.

            When raw_fi is True the signature of open becomes:
                open(self, path, fi)

            and the file handle should be set directly.
            '''

            return 0

        def opendir(self, path):
            'Returns a numerical file handle.'

            return 0

        def read(self, path, size, offset, fh):
            'Returns a string containing the data requested.'

            raise FuseOSError(EIO)

        def readdir(self, path, fh):
            '''
            Can return either a list of names, or a list of (name, attrs, offset)
            tuples. attrs is a dict as in getattr.
            '''

            return ['.', '..']

        def readlink(self, path):
            raise FuseOSError(ENOENT)

        def release(self, path, fh):
            return 0

        def releasedir(self, path, fh):
            return 0

        def removexattr(self, path, name):
            raise FuseOSError(ENOTSUP)

        def rename(self, old, new):
            raise FuseOSError(EROFS)

        def rmdir(self, path):
            raise FuseOSError(EROFS)

        def setxattr(self, path, name, value, options, position=0):
            raise FuseOSError(ENOTSUP)

        def statfs(self, path):
            '''
            Returns a dictionary with keys identical to the statvfs C structure of
            statvfs(3).

            On Mac OS X f_bsize and f_frsize must be a power of 2
            (minimum 512).
            '''

            return {}

        def symlink(self, target, source):
            'creates a symlink `target -> source` (e.g. ln -s source target)'

            raise FuseOSError(EROFS)

        def truncate(self, path, length, fh=None):
            raise FuseOSError(EROFS)

        def unlink(self, path):
            raise FuseOSError(EROFS)

        def utimens(self, path, times=None):
            'Times is a (atime, mtime) tuple. If None use current time.'

            return 0

        def write(self, path, data, offset, fh):
            raise FuseOSError(EROFS)


    class LoggingMixIn:
        log = logging.getLogger('fuse.log-mixin')

        def __call__(self, op, path, *args):
            self.log.debug('-> %s %s %s', op, path, repr(args))
            ret = '[Unhandled Exception]'
            try:
                ret = getattr(self, op)(path, *args)
                return ret
            except OSError, e:
                ret = str(e)
                raise
            finally:
                self.log.debug('<- %s %s', op, repr(ret))
#### End of FUSEPY ######
except EnvironmentError:
    HAS_FUSE=False

def printerr(message):
    """ Print given message to stderr with a line feed. """
    print >>sys.stderr, message

class PathError(Exception):
    pass

class ExecutionError(Exception):
    """ Raised by shell() and run() if command returns non-zero exit code. """
    pass

def args_to_list(args):
    """ Return a flat list of the given arguments for shell(). """
    arglist = []
    for arg in args:
        if arg is None:
            continue
        if hasattr(arg, '__iter__'):
            arglist.extend(args_to_list(arg))
        else:
            if not isinstance(arg, basestring):
                arg = str(arg)
            arglist.append(arg)
    return arglist

def shell(*args, **kwargs):
    r""" Run a command: program name is given in first arg and command line
        arguments in the rest of the args. Iterables (lists and tuples) in args
        are recursively converted to separate arguments, non-string types are
        converted with str(arg), and None is ignored. For example:

        >>> def tail(input, n=3, flags=None):
        >>>     args = ['-n', n]
        >>>     return shell('tail', args, flags, input=input)
        >>> tail('a\nb\nc\nd\ne\n')
        'c\nd\ne\n'
        >>> tail('a\nb\nc\nd\ne\n', 2, ['-v'])
        '==> standard input <==\nd\ne\n'

        Keyword arguments kwargs are interpreted as follows:

        "input" is a string to pass standard input into the process (or the
            default of None to use parent's stdin, eg: the keyboard)
        "silent" is True (default) to return process's standard output as a
            string, or False to print it as it comes out
        "shell" set to True will run the command via the shell (/bin/sh or
            COMSPEC) instead of running the command directly (the default)
        "ignore_status" set to True means ignore command status code -- i.e.,
            don't raise an ExecutionError on nonzero status code
        Any other kwargs are passed directly to subprocess.Popen
        Raises ExecutionError(message, output, status) if the command returns
        a non-zero status code. """
    try:
        return _shell(args, **kwargs)
    finally:
        sys.stderr.flush()
        sys.stdout.flush()

def _shell(args, input=None, silent=True, shell=False, ignore_status=False, **kwargs):
    if input:
        stdin = subprocess.PIPE
    else:
        stdin = None
    if silent:
        stdout = subprocess.PIPE
    else:
        stdout = None
    arglist = args_to_list(args)
    logger.debug("Running shell %s", arglist)
    if not arglist:
        raise TypeError('shell() takes at least 1 argument (0 given)')
    if shell:
        # handle subprocess.Popen quirk where subsequent args are passed
        # to bash instead of to our command
        command = subprocess.list2cmdline(arglist)
    else:
        command = arglist
    try:
        proc = subprocess.Popen(command, stdin=stdin, stdout=stdout,
                                stderr=subprocess.STDOUT, shell=shell, **kwargs)
    except OSError, e:
        # Work around the problem that Windows Popen doesn't say what file it couldn't find
        if platform.system() == 'Windows' and e.errno == 2 and e.filename is None:
            e.filename = arglist[0]
        raise e
    output, stderr = proc.communicate(input)
    status = proc.wait()
    if status and not ignore_status:
        raise ExecutionError('%r exited with status %d'
                             % (os.path.basename(arglist[0]), status),
                             output, status)
    if silent:
        return output

def md5_hasher(filename):
    """ Return MD5 hash of given filename if it is a regular file or
        a symlink with a hashable target, or the MD5 hash of the
        target_filename if it is a symlink without a hashable target,
        or the MD5 hash of the filename if it is a directory, or None
        if file doesn't exist.

        Note: Pyhton versions before 3.2 do not support os.readlink on
        Windows so symlinks without a hashable target fall back to
        a hash of the filename if the symlink target is a directory,
        or None if the symlink is broken"""
    try:
        f = open(filename, 'rb')
        try:
            return md5func(f.read()).hexdigest()
        finally:
            f.close()
    except IOError:
        if hasattr(os, 'readlink') and os.path.islink(filename):
            return md5func(os.readlink(filename)).hexdigest()
        elif os.path.isdir(filename):
            return md5func(filename).hexdigest()
        return None

def mtime_hasher(filename):
    """ Return modification time of file, or None if file doesn't exist. """
    try:
        st = os.stat(filename)
        return repr(st.st_mtime)
    except (IOError, OSError):
        return None

class RunnerUnsupportedException(Exception):
    """ Exception raise by Runner constructor if it is not supported
        on the current platform."""
    pass

class Runner(object):
    def __call__(self, *args, **kwargs):
        """ Run command and return (dependencies, outputs), where
            dependencies is a list of the filenames of files that the
            command depended on, and output is a list of the filenames
            of files that the command modified. The input is passed
            to shell()"""
        raise NotImplementedError("Runner subclass called but subclass didn't define __call__")

    def actual_runner(self):
        """ Return the actual runner object (overriden in SmartRunner). """
        return self

    def ignore(self, name):
        return self._builder.ignore.search(name)

    def cleanup(self):
        """ clean up method"""
        pass

class FileOperationRunner(Runner):
    """ Base class for all Runners that track file operations to
        calculate the depedencies"""
    def __init__(self, build_dir=None):
        self._build_dir = os.path.normcase(os.path.abspath(build_dir or os.getcwd()))
    
    def _get_relevant_name(self, name):
        """ Returns a normalised path that is relative to the build 
            directory if path lies within the build directoy. Returns 
            None if the file should be ignored as it therfore not
            relevant to the build"""
        # normalise path name to ensure files are only listed once
        name = os.path.normcase(os.path.normpath(name))
        
        # if it's an absolute path name under the build directory,
        # make it relative to build_dir before saving to .deps file
        if os.path.isabs(name) and name.startswith(self._build_dir):
            name = name[len(self._build_dir):]
            name = name.lstrip(os.path.sep)

        if (self._builder._is_relevant(name) 
            and not self.ignore(name) 
            and os.path.lexists(name)):
            return name
        return None
        
class TrackerRunner(FileOperationRunner):
    _tracker_exe = os.path.join(os.path.dirname(__file__), 'tracker', 'Tracker.exe')

    def __init__(self, builder, *args, **kwargs):
        FileOperationRunner.__init__(self, *args, **kwargs)
        self._builder = builder
        if not os.path.isfile(TrackerRunner._tracker_exe):
            raise RunnerUnsupportedException(
                'tracker.exe is not supported on this platform')

    def parse_touched(self, tlogFN):
        deps = set()
        with codecs.open(tlogFN, 'r', 'utf-16') as tlog:
            lines_iter = iter(tlog) 
            lines_iter.next()  # skip first line 
            for name in lines_iter:
                name = self._get_relevant_name(name.strip('\r\n'))
                if name is not None:
                    deps.add(name)
        return list(deps)

    def __call__(self, *args, **kwargs):
        tmpd = tempfile.mkdtemp(suffix='tracker')
        if not os.path.isdir(tmpd):
            raise RunnerUnsupportedException('failed to create a temporary directory for tracker')
        shell_keywords = dict(silent=False)
        shell_keywords.update(kwargs)
        shell(TrackerRunner._tracker_exe, '/if', tmpd, '/e', '/c', args, **shell_keywords)
        # dig through all the *.tlog files and get the files touched
        alldeps     = []
        allouts     = []
        for tlog in glob.glob(os.path.join(tmpd, '*.read.*')):
            deps = self.parse_touched(os.path.join(tmpd, tlog))
            alldeps.extend(deps)
        for tlog in glob.glob(os.path.join(tmpd, '*.write.*')):
            outs = self.parse_touched(os.path.join(tmpd, tlog))
            allouts.extend(outs)
        shutil.rmtree(tmpd)
        gc.collect()
        return alldeps, allouts

        
def _call_strace(self, *args, **kwargs):
    """ Top level function call for Strace that can be run in parallel """
    return self(*args, **kwargs)

class AlwaysRunner(Runner):
    def __init__(self, builder):
        pass

    def __call__(self, *args, **kwargs):
        """ Runner that always runs given command, used as a backup in case
            a system doesn't have strace or atimes. """
        shell_keywords = dict(silent=False)
        shell_keywords.update(kwargs)
        shell(*args, **shell_keywords)
        return None, None

class SmartRunner(Runner):
    """ Smart command runner that uses TrackerRunner if it can, else tries with FuseRunner
        if available, otherwise AlwaysRunner. """
    def __init__(self, builder):
        self._builder = builder
        try:
            if os.name == 'nt':
                self._runner = TrackerRunner(self._builder)
            else:
                self._runner = FuseRunner(self._builder)
        except RunnerUnsupportedException:
                self._runner = AlwaysRunner(self._builder)

    def actual_runner(self):
        return self._runner

    def __call__(self, *args, **kwargs):
        return self._runner(*args, **kwargs)

class _running(object):
    """ Represents a task put on the parallel pool
        and its results when complete """
    def __init__(self, async, command):
        """ "async" is the AsyncResult object returned from pool.apply_async
            "command" is the command that was run """
        self.async = async
        self.command = command
        self.results = None

class _after(object):
    """ Represents something waiting on completion of some previous commands """
    def __init__(self, afters, do):
        """ "afters" is a group id or a iterable of group ids to wait on
            "do" is either a tuple representing a command (group, command,
                arglist, kwargs) or a threading.Condition to be released """
        self.afters = afters
        self.do = do
        self.done = False

class _Groups(object):
    """ Thread safe mapping object whose values are lists of _running
        or _after objects and a count of how many have *not* completed """
    class value(object):
        """ the value type in the map """
        def __init__(self, val=None):
            self.count = 0  # count of items not yet completed.
                            # This also includes count_in_false number
            self.count_in_false = 0  # count of commands which is assigned
                                     # to False group, but will be moved
                                     # to this group.
            self.items = [] # items in this group
            if val is not None:
                self.items.append(val)
            self.ok = True  # True if no error from any command in group so far

    def __init__(self):
        self.groups = {False: self.value()}
        self.lock = threading.Lock()

    def item_list(self, id):
        """ Return copy of the value list """
        with self.lock:
            try:
                return self.groups[id].items[:]
            except KeyError,e:
                logger.error("item_list: no group %s found", id)
                raise e

    def remove(self, id):
        """ Remove the group """
        with self.lock:
            try:
                del self.groups[id]
            except KeyError,e:
                logger.error("remove: no group %s found", id)
                raise e

    def remove_item(self, id, val):
        with self.lock:
            try:
                self.groups[id].items.remove(val)
            except KeyError,e:
                logger.error("remove_item: no group %s found or item %s", id,
                        val)
                raise e

    def add(self, id, val):
        with self.lock:
            if id in self.groups:
                self.groups[id].items.append(val)
            else:
                self.groups[id] = self.value(val)
            self.groups[id].count += 1

    def ensure(self, id):
        """if id does not exit, create it without any value"""
        with self.lock:
            if not id in self.groups:
                self.groups[id] = self.value()

    def get_count(self, id):
        with self.lock:
            if id not in self.groups:
                return 0
            return self.groups[id].count

    def dec_count(self, id):
        with self.lock:
            try:
                c = self.groups[id].count - 1
            except KeyError,e:
                logger.error("dec_count: no group %s found", id)
                raise e
            if c < 0:
                raise ValueError
            self.groups[id].count = c
            return c

    def get_ok(self, id):
        with self.lock:
            try:
                return self.groups[id].ok
            except KeyError,e:
                logger.warning("No group %s found — assuming associated files exists", id)
                return True

    def set_ok(self, id, to):
        with self.lock:
            try:
                self.groups[id].ok = to
            except KeyError,e:
                logger.error("set_ok: no group %s found", id)
                raise e

    def ids(self):
        with self.lock:
            return self.groups.keys()

    # modification to reserve blocked commands to corresponding groups
    def inc_count_for_blocked(self, id):
        with self.lock:
            if not id in self.groups:
                self.groups[id] = self.value()
            self.groups[id].count += 1
            self.groups[id].count_in_false += 1

    def add_for_blocked(self, id, val):
        # modification of add(), in order to move command from False group
        # to actual group
        with self.lock:
            # id must be registered before
            try:
                self.groups[id].items.append(val)
            except KeyError,e:
                logger.error("set_ok: no group %s found or %s in it", id, val)
                raise e
            # count does not change (already considered
            # in inc_count_for_blocked), but decrease count_in_false.
            c = self.groups[id].count_in_false - 1
            if c < 0:
                raise ValueError
            self.groups[id].count_in_false = c


# pool of processes to run parallel jobs, must not be part of any object that
# is pickled for transfer to these processes, ie it must be global
_pool = None
# object holding results, must also be global
_groups = _Groups()
# results collecting thread
_results = None
_stop_results = threading.Event()

class _todo(object):
    """ holds the parameters for commands waiting on others """
    def __init__(self, group, command, arglist, kwargs):
        self.group = group      # which group it should run as
        self.command = command  # string command
        self.arglist = arglist  # command arguments
        self.kwargs = kwargs    # keywork args for the runner

def _results_handler( builder, delay=0.01):
    """ Body of thread that stores results in .deps and handles 'after'
        conditions
       "builder" the builder used """
    try:
        while not _stop_results.isSet():

            # go through the lists and check any results available
            for id in _groups.ids():
                if id is False: continue # key of False is _afters not _runnings
                for r in _groups.item_list(id):
                    if r.results is None and r.async.ready():
                        try:
                            d, o = r.async.get()
                        except Exception, e:
                            r.results = e
                            _groups.set_ok(id, False)
                            message, data, status = e
                            printerr("fabricate: " + message)
                        else:
                            logger.debug("Done %s: %s",  id, r.command)
                            builder.done(r.command, d, o) # save deps
                            r.results = (r.command, d, o)
                        _groups.dec_count(id)
            # check if can now schedule things waiting on the after queue
            for a in _groups.item_list(False):
                still_to_do = sum(_groups.get_count(g) for g in a.afters)
                no_error = all(_groups.get_ok(g) for g in a.afters)
                if False in a.afters:
                    still_to_do -= 1 # don't count yourself of course
                if still_to_do == 0:
                    logger.debug("All done in %s, doing %s", a.afters, a.do)
                    if isinstance(a.do, _todo):
                        if no_error:
                            logger.debug(" Running %s %s", a.do.arglist,
                                a.do.kwargs)
                            async = _pool.apply_async(_call_strace, a.do.arglist,
                                        a.do.kwargs)
                            _groups.add_for_blocked(a.do.group, _running(async, a.do.command))
                        else:
                            # Mark the command as not done due to errors
                            r = _running(None, a.do.command)
                            _groups.add_for_blocked(a.do.group, r)
                            r.results = False;
                            _groups.set_ok(a.do.group, False)
                            _groups.dec_count(a.do.group)
                    elif isinstance(a.do, threading._Condition):
                        # is this only for threading._Condition in after()?
                        a.do.acquire()
                        # only mark as done if there is no error
                        a.done = no_error
                        a.do.notify()
                        a.do.release()
                    # else: #are there other cases?
                    _groups.remove_item(False, a)
                    _groups.dec_count(False)

            _stop_results.wait(delay)
    except Exception:
        etype, eval, etb = sys.exc_info()
        printerr("Error: exception " + repr(etype) + " at line " + str(etb.tb_lineno))
    finally:
        if not _stop_results.isSet():
            # oh dear, I am about to die for unexplained reasons, stop the whole
            # app otherwise the main thread hangs waiting on non-existant me,
            # Note: sys.exit() only kills me
            printerr("Error: unexpected results handler exit")
            os._exit(1)

if HAS_FUSE:
    class FuseRunner(Runner):

        def __init__(self, builder, build_dir=None):
            self._builder = builder
            self.temp_count = 0
            self.build_dir = os.path.abspath(build_dir or os.getcwd())
            self.mountdir = os.path.join(self.build_dir, '.fusefab',
                                        str(os.getpid()))
            os.makedirs(self.mountdir)
            self.cleaned_up = False
            self.signal_file = ".fuserunner%s"%os.getpid()
            self._q = multiprocessing.Queue()
            self.logfsops = LogPassthrough(self.build_dir, os.getpgid(0), self._q,
                                        self.signal_file)
            def mount():
                try:
                    FUSE(self.logfsops, self.mountdir, foreground=True)
                except (RuntimeError, NameError):
                    raise RunnerUnsupportedException()
            # Mount logging FS in separate process
            self._p = multiprocessing.Process(target=mount)
            self._p.daemon = True
            self._p.start()
            while not os.path.ismount(self.mountdir):
                logger.debug("not mounted")
                time.sleep(0.01)
            logger.debug("mounted %s on %s", self.build_dir, self.mountdir)


        def __call__(self, *args, **kwargs):
            prevdir = os.getcwd()
            os.chdir(self.mountdir)
            # run command
            logger.debug("Running %s %s in %s", str(args), str(kwargs), os.getcwd())
            sigfd = os.open(self.signal_file, os.O_WRONLY | os.O_CREAT)
            shell_keywords = dict(silent=False)
            shell_keywords.update(kwargs)
            try:
                res = shell(*args, **shell_keywords)
            except Exception,e:
                printerr(e)
                raise e
            else:
                logger.debug("Result = %s" % res)
            finally:
                os.close(sigfd)
                deps, outputs = self._q.get()
                logger.debug("\nOUT:%s\nDEP:%s", outputs, deps)
                logger.debug("Removing %s  in %s", self.signal_file, os.getcwd())
                os.unlink(self.signal_file)
                os.chdir(prevdir)
            return list(deps), list(outputs)

        def cleanup(self):
            logger.debug('Cleaning up')
            if not self.cleaned_up:
                logger.debug("unmounting %s on %s", self.build_dir, self.mountdir)

                while subprocess.call("fusermount -u %s" % self.mountdir, shell=True):
                    logger.warn("Retrying to unmount local fuse FS…")
                    time.sleep(1)
                #self._p.join()
                os.rmdir(self.mountdir)
            self.cleaned_up = True
else:
    class FuseRunner(Runner):
        def __init__(self, builder, build_dir=None):
            raise RunnerUnsupportedException()

class Builder(object):
    """ The Builder.

        You may supply a "runner" class to change the way commands are run
        or dependencies are determined. For an example, see:
            http://code.google.com/p/fabricate/wiki/HowtoMakeYourOwnRunner

        A "runner" must be a subclass of Runner and must have a __call__()
        function that takes a command as a list of args and returns a tuple of
        (deps, outputs), where deps is a list of rel-path'd dependency files
        and outputs is a list of rel-path'd output files. The default runner
        is SmartRunner, which automatically picks one of TrackerRunner,
        FuseRunner, or AlwaysRunner depending on your system.
        A "runner" class may have an __init__() function that takes the
        builder as a parameter.
    """

    def __init__(self, runner=None, dirs=None, dirdepth=100, ignoreprefix='.',
                 ignore=None, hasher=md5_hasher, depsname='.deps',
                 quiet=False, debug=False, inputs_only=False, parallel_ok=False):
        """ Initialise a Builder with the given options.

        "runner" specifies how programs should be run.  It is either a
            callable compatible with the Runner class, or a string selecting
            one of the standard runners ("tracker_runner", "fuse_runner",
            "always_runner", or "smart_runner").
        "dirs" is a list of paths to look for dependencies (or outputs) in
            if using the strace or atimes runners.
        "dirdepth" is the depth to recurse into the paths in "dirs" (default
            essentially means infinitely). Set to 1 to just look at the
            immediate paths in "dirs" and not recurse at all. This can be
            useful to speed up the AtimesRunner if you're building in a large
            tree and you don't care about all of the subdirectories.
        "ignoreprefix" prevents recursion into directories that start with
            prefix.  It defaults to '.' to ignore svn directories.
            Change it to '_svn' if you use _svn hidden directories.
        "ignore" is a regular expression.  Any dependency that contains a
            regex match is ignored and not put into the dependency list.
            Note that the regex may be VERBOSE (spaces are ignored and # line
            comments allowed -- use \ prefix to insert these characters)
        "hasher" is a function which returns a string which changes when
            the contents of its filename argument changes, or None on error.
            Default is md5_hasher, but can also be mtime_hasher.
        "depsname" is the name of the JSON dependency file to load/save.
        "quiet" set to True tells the builder to not display the commands being
            executed (or other non-error output).
        "debug" set to True makes the builder print debug output, such as why
            particular commands are being executed
        "inputs_only" set to True makes builder only re-build if input hashes
            have changed (ignores output hashes); use with tools that touch
            files that shouldn't cause a rebuild; e.g. g++ collect phase
        "parallel_ok" set to True to indicate script is safe for parallel running
        """
        if dirs is None:
            dirs = ['.']
        self.dirs = dirs
        self.dirdepth = dirdepth
        self.ignoreprefix = ignoreprefix
        if ignore is None:
            ignore = r'$x^'         # something that can't match
        self.ignore = re.compile(ignore, re.VERBOSE)
        self.depsname = depsname
        self.hasher = hasher
        self.quiet = quiet
        self.debug = debug
        self.inputs_only = inputs_only
        self.checking = False
        self.hash_cache = {}

        # instantiate runner after the above have been set in case it needs them
        if runner is not None:
            self.set_runner(runner)
        elif hasattr(self, 'runner'):
            # For backwards compatibility, if a derived class has
            # defined a "runner" method then use it:
            pass
        else:
            self.runner = SmartRunner(self)

        is_file_op_runner = isinstance(self.runner.actual_runner(), FileOperationRunner)
        logger.debug("### actual_runner: %s", self.runner.actual_runner())
        logger.debug("### is_file_op_runner: %s", is_file_op_runner)
        self.parallel_ok = parallel_ok and is_file_op_runner and _pool is not None
        logger.debug("### parallel_ok: %s", self.parallel_ok)
        if self.parallel_ok:
            global _results
            _results = threading.Thread(target=_results_handler,
                                        args=[self])
            _results.setDaemon(True)
            _results.start()
            atexit.register(self._join_results_handler)

    def echo(self, message):
        """ Print message, but only if builder is not in quiet mode. """
        if not self.quiet:
            #print message
            logger.info(message)

    def echo_command(self, command, echo=None):
        """ Show a command being executed. Also passed run's "echo" arg
            so you can override what's displayed.
        """
        if echo is not None:
            command = str(echo)
        self.echo(command)

    def echo_delete(self, filename, error=None):
        """ Show a file being deleted. For subclassing Builder and overriding
            this function, the exception is passed in if an OSError occurs
            while deleting a file. """
        if error is None:
            self.echo('deleting %s' % filename)
        else:
            self.echo_debug('error deleting %s: %s' % (filename, error.strerror))

    def echo_debug(self, message):
        """ Print message, but only if builder is in debug mode. """
        if self.debug:
            logger.debug(message)
            #print 'DEBUG:', message

    def _run(self, *args, **kwargs):
        after = kwargs.pop('after', None)
        group = kwargs.pop('group', True)
        echo = kwargs.pop('echo', None)
        arglist = args_to_list(args)
        if not arglist:
            raise TypeError('run() takes at least 1 argument (0 given)')
        # we want a command line string for the .deps file key and for display
        command = subprocess.list2cmdline(arglist)
        if not self.cmdline_outofdate(command):
            if self.parallel_ok:
                _groups.ensure(group)
            return command, None, None

        # if just checking up-to-date-ness, set flag and do nothing more
        self.outofdate_flag = True
        if self.checking:
            if self.parallel_ok:
                _groups.ensure(group)
            return command, None, None

        # use runner to run command and collect dependencies
        self.echo_command(command, echo=echo)
        if self.parallel_ok:
            arglist.insert(0, self.runner)
            if after is not None:
                if not hasattr(after, '__iter__'):
                    after = [after]
                # This command is registered to False group firstly,
                # but the actual group of this command should
                # count this blocked command as well as usual commands
                logger.debug("Scheduling in group %s after %s:  %s %s", group,
                        after, arglist, kwargs)
                _groups.inc_count_for_blocked(group)
                _groups.add(False,
                            _after(after, _todo(group, command, arglist,
                                                kwargs)))
            else:
                logger.debug("Scheduling in group %s:  %s %s", group, arglist, kwargs)
                async = _pool.apply_async(_call_strace, arglist, kwargs)
                _groups.add(group, _running(async, command))
            return None
        else:
            deps, outputs = self.runner(*arglist, **kwargs)
            self.runner.cleanup()
            return self.done(command, deps, outputs)

    def run(self, *args, **kwargs):
        """ Run command given in args with kwargs per shell(), but only if its
            dependencies or outputs have changed or don't exist. Return tuple
            of (command_line, deps_list, outputs_list) so caller or subclass
            can use them.

            Parallel operation keyword args "after" specifies a group or
            iterable of groups to wait for after they finish, "group" specifies
            the group to add this command to.

            Optional "echo" keyword arg is passed to echo_command() so you can
            override its output if you want.
        """
        try:
            return self._run(*args, **kwargs)
        finally:
            self.runner.cleanup()
            sys.stderr.flush()
            sys.stdout.flush()

    def done(self, command, deps, outputs):
        """ Store the results in the .deps file when they are available """
        if deps is not None or outputs is not None:
            deps_dict = {}

            # hash the dependency inputs and outputs
            for dep in deps:
                if dep in self.hash_cache:
                    # already hashed so don't repeat hashing work
                    hashed = self.hash_cache[dep]
                else:
                    hashed = self.hasher(dep)
                if hashed is not None:
                    deps_dict[dep] = "input-" + hashed
                    # store hash in hash cache as it may be a new file
                    self.hash_cache[dep] = hashed

            for output in outputs:
                hashed = self.hasher(output)
                if hashed is not None:
                    deps_dict[output] = "output-" + hashed
                    # update hash cache as this file should already be in
                    # there but has probably changed
                    self.hash_cache[output] = hashed

            self.deps[command] = deps_dict

        return command, deps, outputs

    def memoize(self, command, **kwargs):
        """ Run the given command, but only if its dependencies have changed --
            like run(), but returns the status code instead of raising an
            exception on error. If "command" is a string (as per memoize.py)
            it's split into args using shlex.split() in a POSIX/bash style,
            otherwise it's a list of args as per run().

            This function is for compatiblity with memoize.py and is
            deprecated. Use run() instead. """
        if isinstance(command, basestring):
            args = shlex.split(command)
        else:
            args = args_to_list(command)
        try:
            self.run(args, **kwargs)
            status = 0
        except ExecutionError, exc:
            message, data, status = exc
        finally:
            self.runner.cleanup()

        return status

    def outofdate(self, func):
        """ Return True if given build function is out of date. """
        self.checking = True
        self.outofdate_flag = False
        func()
        self.checking = False
        return self.outofdate_flag

    def cmdline_outofdate(self, command):
        """ Return True if given command line is out of date. """
        if command in self.deps:
            # command has been run before, see if deps have changed
            for dep, oldhash in self.deps[command].items():
                assert oldhash.startswith('input-') or \
                       oldhash.startswith('output-'), \
                    "%s file corrupt, do a clean!" % self.depsname
                io_type, oldhash = oldhash.split('-', 1)

                # make sure this dependency or output hasn't changed
                if dep in self.hash_cache:
                    # already hashed so don't repeat hashing work
                    newhash = self.hash_cache[dep]
                else:
                    # not in hash_cache so make sure this dependency or
                    # output hasn't changed
                    newhash = self.hasher(dep)
                    if newhash is not None:
                       # Add newhash to the hash cache
                       self.hash_cache[dep] = newhash

                if newhash is None:
                    self.echo_debug("rebuilding %r, %s %s doesn't exist" %
                                    (command, io_type, dep))
                    break
                if newhash != oldhash and (not self.inputs_only or io_type == 'input'):
                    self.echo_debug("rebuilding %r, hash for %s %s (%s) != old hash (%s)" %
                                    (command, io_type, dep, newhash, oldhash))
                    break
            else:
                # all dependencies are unchanged
                return False
        else:
            self.echo_debug('rebuilding %r, no dependency data' % command)
        # command has never been run, or one of the dependencies didn't
        # exist or had changed
        return True

    def autoclean(self):
        """ Automatically delete all outputs of this build as well as the .deps
            file. """
        # first build a list of all the outputs from the .deps file
        outputs = []
        dirs = []
        for command, deps in self.deps.items():
            outputs.extend(dep for dep, hashed in deps.items()
                           if hashed.startswith('output-'))
        outputs.append(self.depsname)
        self._deps = None
        for output in outputs:
            try:
                os.remove(output)
            except OSError, e:
                if os.path.isdir(output):
                    # cache directories to be removed once all other outputs
                    # have been removed, as they may be content of the dir
                    dirs.append(output)
                else:
                    self.echo_delete(output, e)
            else:
                self.echo_delete(output)
        # delete the directories in reverse sort order
        # this ensures that parents are removed after children
        for dir in sorted(dirs, reverse=True):
            try:
                os.rmdir(dir)
            except OSError, e:
                self.echo_delete(dir, e)
            else:
                self.echo_delete(dir)


    @property
    def deps(self):
        """ Lazy load .deps file so that instantiating a Builder is "safe". """
        if not hasattr(self, '_deps') or self._deps is None:
            self.read_deps()
            atexit.register(self.write_deps, depsname=os.path.abspath(self.depsname))
        return self._deps

    def read_deps(self):
        """ Read dependency JSON file into deps object. """
        try:
            f = open(self.depsname)
            try:
                self._deps = json.load(f)
                # make sure the version is correct
                if self._deps.get('.deps_version', 0) != deps_version:
                    printerr('Bad %s dependency file version! Rebuilding.'
                             % self.depsname)
                    self._deps = {}
                self._deps.pop('.deps_version', None)
            finally:
                f.close()
        except IOError:
            self._deps = {}

    def write_deps(self, depsname=None):
        """ Write out deps object into JSON dependency file. """
        if self._deps is None:
            return                      # we've cleaned so nothing to save
        self.deps['.deps_version'] = deps_version
        if depsname is None:
            depsname = self.depsname
        f = open(depsname, 'w')
        try:
            json.dump(self.deps, f, indent=4, sort_keys=True)
        finally:
            f.close()
            self._deps.pop('.deps_version', None)

    _runner_map = {
        'always_runner' : AlwaysRunner,
        'smart_runner' : SmartRunner,
        'fuse_runner' : FuseRunner,
        'tracker_runner' : TrackerRunner,
        }

    def set_runner(self, runner):
        """Set the runner for this builder.  "runner" is either a Runner
           subclass (e.g. SmartRunner), or a string selecting one of the
           standard runners ("tracker_runner", "fuse_runner",
           "always_runner", or "smart_runner")."""
        try:
            self.runner = self._runner_map[runner](self)
        except KeyError:
            if isinstance(runner, basestring):
                # For backwards compatibility, allow runner to be the
                # name of a method in a derived class:
                self.runner = getattr(self, runner)
            else:
                # pass builder to runner class to get a runner instance
                self.runner = runner(self)

    def _is_relevant(self, fullname):
        """ Return True if file is in the dependency search directories. """

        # need to abspath to compare rel paths with abs
        fullname = os.path.abspath(fullname)
        for path in self.dirs:
            path = os.path.abspath(path)
            if fullname.startswith(path):
                rest = fullname[len(path):]
                # files in dirs starting with ignoreprefix are not relevant
                if os.sep+self.ignoreprefix in os.sep+os.path.dirname(rest):
                    continue
                # files deeper than dirdepth are not relevant
                if rest.count(os.sep) > self.dirdepth:
                    continue
                return True
        return False

    def _join_results_handler(self):
        """Stops then joins the results handler thread"""
        _stop_results.set()
        _results.join()

# default Builder instance, used by helper run() and main() helper functions
default_builder = None
default_command = 'build'

# save the setup arguments for use by main()
_setup_builder = None
_setup_default = None
_setup_kwargs = {}

def setup(builder=None, default=None, **kwargs):
    """ NOTE: setup functionality is now in main(), setup() is kept for
        backward compatibility and should not be used in new scripts.

        Setup the default Builder (or an instance of given builder if "builder"
        is not None) with the same keyword arguments as for Builder().
        "default" is the name of the default function to run when the build
        script is run with no command line arguments. """
    global _setup_builder, _setup_default, _setup_kwargs
    _setup_builder = builder
    _setup_default = default
    _setup_kwargs = kwargs
setup.__doc__ += '\n\n' + Builder.__init__.__doc__

def _set_default_builder():
    """ Set default builder to Builder() instance if it's not yet set. """

    global default_builder
    if default_builder is None:
        default_builder = Builder()

def run(*args, **kwargs):
    """ Run the given command, but only if its dependencies have changed. Uses
        the default Builder. Return value as per Builder.run(). If there is
        only one positional argument which is an iterable treat each element
        as a command, returns a list of returns from Builder.run().
    """
    _set_default_builder()
    if len(args) == 1 and hasattr(args[0], '__iter__'):
        return [default_builder.run(*a, **kwargs) for a in args[0]]
    return default_builder.run(*args, **kwargs)

def after(*args):
    """ wait until after the specified command groups complete and return
        results, or None if not parallel """
    _set_default_builder()
    if getattr(default_builder, 'parallel_ok', False):
        if len(args) == 0:
            args = _groups.ids()  # wait on all
        cond = threading.Condition()
        cond.acquire()
        a = _after(args, cond)
        _groups.add(False, a)
        cond.wait()
        if not a.done:
            sys.exit(1)
        results = []
        ids = _groups.ids()
        for a in args:
            if a in ids and a is not False:
                r = []
                for i in _groups.item_list(a):
                    r.append(i.results)
                results.append((a,r))
        return results
    else:
        return None

def autoclean():
    """ Automatically delete all outputs of the default build. """
    _set_default_builder()
    default_builder.autoclean()

def memoize(command, **kwargs):
    _set_default_builder()
    return default_builder.memoize(command, **kwargs)

memoize.__doc__ = Builder.memoize.__doc__

def outofdate(command):
    """ Return True if given command is out of date and needs to be run. """
    _set_default_builder()
    return default_builder.outofdate(command)

# save options for use by main() if parse_options called earlier by user script
_parsed_options = None

# default usage message
_usage = '[options] build script functions to run'

def parse_options(usage=_usage, extra_options=None, command_line=None):
    """ Parse command line options and return (parser, options, args). """
    parser = optparse.OptionParser(usage='Usage: %prog '+usage,
                                   version='%prog '+__version__)
    parser.disable_interspersed_args()
    parser.add_option('-t', '--time', action='store_true',
                      help='use file modification times instead of MD5 sums')
    parser.add_option('-d', '--dir', action='append',
                      help='add DIR to list of relevant directories')
    parser.add_option('-c', '--clean', action='store_true',
                      help='autoclean build outputs before running')
    parser.add_option('-q', '--quiet', action='store_true',
                      help="don't echo commands, only print errors")
    parser.add_option('-D', '--debug', action='store_true',
                      help="show debug info (why commands are rebuilt)")
    parser.add_option('-k', '--keep', action='store_true',
                      help='keep temporary strace output files')
    parser.add_option('-j', '--jobs', type='int',
                      help='maximum number of parallel jobs')
    if extra_options:
        # add any user-specified options passed in via main()
        for option in extra_options:
            parser.add_option(option)
    if command_line is not None:
        options, args = parser.parse_args(command_line)
    else:
        options, args = parser.parse_args()
    _parsed_options = (parser, options, args)
    return _parsed_options

def fabricate_version(min=None, max=None):
    """ If min is given, assert that the running fabricate is at least that
        version or exit with an error message. If max is given, assert that
        the running fabricate is at most that version. Return the current
        fabricate version string. This function was introduced in v1.14;
        for prior versions, the version string is available only as module
        local string fabricate.__version__ """

    if min is not None and float(__version__) < min:
        sys.stderr.write(("fabricate is version %s.  This build script "
            "requires at least version %.2f") % (__version__, min))
        sys.exit()
    if max is not None and float(__version__) > max:
        sys.stderr.write(("fabricate is version %s.  This build script "
            "requires at most version %.2f") % (__version__, max))
        sys.exit()
    return __version__

def main(globals_dict=None, build_dir=None, extra_options=None, builder=None,
         default=None, jobs=1, command_line=None, **kwargs):
    """ Run the default function or the function(s) named in the command line
        arguments. Call this at the end of your build script. If one of the
        functions returns nonzero, main will exit with the last nonzero return
        value as its status code.

        "builder" is the class of builder to create, default (None) is the
        normal builder
        "command_line" is an optional list of command line arguments that can
        be used to prevent the default parsing of sys.argv. Used to intercept
        and modify the command line passed to the build script.
        "default" is the default user script function to call, None = 'build'
        "extra_options" is an optional list of options created with
        optparse.make_option(). The pseudo-global variable main.options
        is set to the parsed options list.
        "kwargs" is any other keyword arguments to pass to the builder """
    global default_builder, default_command, _pool

    kwargs.update(_setup_kwargs)
    if _parsed_options is not None:
        parser, options, actions = _parsed_options
    else:
        parser, options, actions = parse_options(extra_options=extra_options, command_line=command_line)
    kwargs['quiet'] = options.quiet
    kwargs['debug'] = options.debug
    if options.time:
        kwargs['hasher'] = mtime_hasher
    if options.dir:
        kwargs['dirs'] = options.dir
    main.options = options
    if options.jobs is not None:
        jobs = options.jobs
    if default is not None:
        default_command = default
    if default_command is None:
        default_command = _setup_default
    if not actions:
        actions = [default_command]

    original_path = os.getcwd()
    if None in [globals_dict, build_dir]:
        try:
            frame = sys._getframe(1)
        except:
            printerr("Your Python version doesn't support sys._getframe(1),")
            printerr("call main(globals(), build_dir) explicitly")
            sys.exit(1)
        if globals_dict is None:
            globals_dict = frame.f_globals
        if build_dir is None:
            build_file = frame.f_globals.get('__file__', None)
            if build_file:
                build_dir = os.path.dirname(build_file)
    if build_dir:
        if not options.quiet and os.path.abspath(build_dir) != original_path:
            print "Entering directory '%s'" % build_dir
        os.chdir(build_dir)
    if _pool is None and jobs > 1:
        _pool = multiprocessing.Pool(jobs)

    use_builder = Builder
    if _setup_builder is not None:
        use_builder = _setup_builder
    if builder is not None:
        use_builder = builder
    default_builder = use_builder(**kwargs)

    if options.clean:
        default_builder.autoclean()

    status = 0
    try:
        for action in actions:
            if '(' not in action:
                action = action.strip() + '()'
            name = action.split('(')[0].split('.')[0]
            if name in globals_dict:
                this_status = eval(action, globals_dict)
                if this_status:
                    status = int(this_status)
            else:
                printerr('%r command not defined!' % action)
                sys.exit(1)
        after() # wait till the build commands are finished
    except ExecutionError, exc:
        message, data, status = exc
        printerr('fabricate: ' + message)
    finally:
        _stop_results.set() # stop the results gatherer so I don't hang
        if not options.quiet and os.path.abspath(build_dir) != original_path:
            print "Leaving directory '%s' back to '%s'" % (build_dir, original_path)
        os.chdir(original_path)
        default_builder.runner.cleanup()
    sys.exit(status)

if HAS_FUSE:
    class LogPassthrough(LoggingMixIn, Operations):
        """ Filesystems that pass through standard file systems, but logs reading
            and writing operations
        """
        def __init__(self, root, ourpgid, queue, signalfile):
            """
            Initializing LogPassthrough object.

            :param str root: root path
            :param int ourpgid: process group id of fabricate
            :param Queue queue: queue use to cummunicate between main and fuse process.
            :param str signalfile: filename used to trigger log flusshing and
                    message passing over queue.
                    Creating the file triggers the flush of the logs in the fuse process.
                    Removing the file triggers the sending of message over the queue.
            """
            self.root = os.path.realpath(root)
            self.rwlock = multiprocessing.Lock()
            self.deps = set()
            self.outputs = set()
            self.ourpgid = ourpgid
            self.queue = queue
            self.signalfile = signalfile

        def clean_logs(self):
            self.deps = set()
            self.outputs = set()

        def __call__(self, op, path, *args):
            logger.debug("### %s %s", op, path)
            logger.debug("deps = %s", self.deps)
            logger.debug("outputs = %s", self.outputs)
            _, _, pid = fuse_get_context()
            if os.getpgid(pid) != self.ourpgid:
                logger.debug("Process pid=%d is trying to acces the "
                            "fabric fuse fs for '%s' in %s",pid, op, path)
                return {}
            else:
                # remove leading / from path
                return super(LogPassthrough, self).__call__(op, path[1:], *args)


        def _full_path(self, path):
            res = os.path.join(self.root, path)
            return res
        # Filesystem methods
        # ==================


        def access(self, path, mode):
            self.deps.add(path)
            if os.access(self._full_path(path), mode):
                return 0
            else:
                return -1


        def chmod(self, path, mode):
            #self.outputs.add(path)
            return os.chmod(self._full_path(path), mode)

        def chown(self, path, uid, gid):
            #self.outputs.add(path)
            return os.chown(self._full_path(path), uid, gid)

        def getattr(self, path, fh=None):
            if path != self.signalfile:
                self.deps.add(path)
            st = os.lstat(self._full_path(path))
            return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                        'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

        def readdir(self, path, fh):
            self.deps.add(path)
            dirents = ['.', '..']
            if os.path.isdir(self._full_path(path)):
                dirents.extend(os.listdir(self._full_path(path)))
            for r in dirents:
                yield r

        def readlink(self, path):
            pathname = os.readlink(self._full_path(path))
            self.deps.add(path)
            if pathname.startswith("/"):
                # Path name is absolute, sanitize it.
                return os.path.relpath(pathname, self.root)
            else:
                return pathname

        def mknod(self, path, mode, dev):
            self.outputs.add(path)
            self.deps.discard(path)
            return os.mknod(self._full_path(path), mode, dev)

        def rmdir(self, path):
            self.outputs.add(path)
            self.deps.discard(path)
            return os.rmdir(self._full_path(path))

        def mkdir(self, path, mode):
            self.outputs.add(path)
            self.deps.discard(path)
            return os.mkdir(self._full_path(path), mode)

        def statfs(self, path):
            self.deps.add(path)
            stv = os.statvfs(self._full_path(path))
            return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
                'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
                'f_frsize', 'f_namemax'))

        def unlink(self, path):
            logger.debug("%s %s", path, self.signalfile)
            if path == self.signalfile:
                pass
            else:
                self.outputs.add(path)
                self.deps.discard(path)
            return os.unlink(self._full_path(path))

        def symlink(self, target, source):
            self.outputs.add(target)
            self.deps.discard(target)
            #self.deps.add(source)
            return os.symlink(self._full_path(source), self._full_path(target))

        def rename(self, old, new):
            self.outputs.add(new)
            self.deps.discard(new)
            self.deps.add(old)
            return os.rename(self._full_path(old), self._full_path(new))

        def link(self, target, source):
            self.outputs.add(target)
            self.deps.discard(target)
            self.deps.add(source)
            return os.link(self._full_path(source), self._full_path(target))

        def utimens(self, path, times=None):
            self.deps.add(path)
            return os.utime(self._full_path(path), times)

        # File methods
        # ============

        def open(self, path, flags):
            if (flags & os.O_WRONLY) or (flags & os.O_RDWR):
                self.outputs.add(path)
                self.deps.discard(path)
            else:
                self.deps.add(path)
            return os.open(self._full_path(path), flags)

        def create(self, path, mode, fi=None):
            logger.debug("%s %s", self._full_path(path) , self.signalfile)
            if path == self.signalfile:
                self.clean_logs()
            else:
                self.outputs.add(path)
                self.deps.discard(path)
            return os.open(self._full_path(path), os.O_WRONLY | os.O_CREAT, mode)

        def read(self, path, length, offset, fh):
            self.deps.add(path)
            with self.rwlock:
                os.lseek(fh, offset, os.SEEK_SET)
                return os.read(fh, length)

        def write(self, path, buf, offset, fh):
            self.outputs.add(path)
            self.deps.discard(path)
            with self.rwlock:
                os.lseek(fh, offset, os.SEEK_SET)
                return os.write(fh, buf)

        def truncate(self, path, length, fh=None):
            self.outputs.add(path)
            self.deps.discard(path)
            with open(self._full_path(path), 'r+') as f:
                f.truncate(length)

        def flush(self, path, fh):
            #self.outputs.add(path)
            #self.deps.discard(path)
            return os.fsync(fh)

        def release(self, path, fh):
            if path == self.signalfile:
                self.queue.put([self.deps, self.outputs])
            return os.close(fh)

        def fsync(self, path, fdatasync, fh):
            return self.flush(self._full_path(path), fh)


if __name__ == '__main__':
    # if called as a script, emulate memoize.py -- run() command line
    parser, options, args = parse_options('[options] command line to run')
    status = 0
    if args:
        status = memoize(args)
    elif not options.clean:
        parser.print_help()
        status = 1
    # autoclean may have been used
    sys.exit(status)
