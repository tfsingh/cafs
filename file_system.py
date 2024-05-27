#!/usr/bin/env python

from __future__ import with_statement

import os
import sys
import errno
import json
import inspect
import signal
from constants import INDEX_STORAGE, FILE_STORAGE 

from fuse import FUSE, FuseOSError, Operations, fuse_get_context

calls = []
def collect(ret=None):
    prev_frame = inspect.currentframe().f_back
    func_name = prev_frame.f_code.co_name
    args, _, _, values = inspect.getargvalues(prev_frame)
    arg_list = [(arg, values[arg]) for arg in args]
    calls.append({"function": func_name, "arguments": str(arg_list[1:]), "returned": ret})

class IndexObj:
    def __init__(self, path, obj_type, data=None, stat=None):
        self.path = path
        self.obj_type = obj_type
        self.data = data
        self.stat = stat

def deserialize_index_obj(obj_dict) -> IndexObj:
    return IndexObj(**obj_dict)

class Passthrough(Operations):
    def __init__(self, root):
        self.root = root
        self.index_data = {}

        with open(os.path.join(INDEX_STORAGE, f"{root}.json")) as f:
            self.index_data = json.load(f)

        self.index = {}
        for item, obj_dict in self.index_data.items():
            self.index[item] = deserialize_index_obj(obj_dict)

    # Helpers
    # =======

    def full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]

        file_path = os.path.join(self.root, partial)

        potential_path = self.fetch_file(partial)

        if potential_path:
            file_path = potential_path

        return file_path

    def fetch_file(self, partial):
        file_path = None
        if partial not in self.index:
            return

        item = self.index[partial]

        return item.path

    # Filesystem methods
    # ==================

    def access(self, path, mode):
        collect()
        full_path = self.full_path(path)
        if not os.access(full_path, mode):
            raise FuseOSError(errno.EACCES)

    def chmod(self, path, mode):
        collect()
        full_path = self.full_path(path)
        return os.chmod(full_path, mode)

    def chown(self, path, uid, gid):
        collect()
        full_path = self.full_path(path)
        return os.chown(full_path, uid, gid)

    def getattr(self, path, fh=None):
        path = path[1:]

        if path not in self.index:
            full_path = self.full_path(path)
            print(full_path)
            st = os.lstat(full_path)
            ret = dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                     'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))
            return ret

        item = self.index[path]

        ret = dict((key, item.stat[i]) for key, i in zip(('st_atime', 'st_ctime',
                     'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'), (7, 9, 5, 0, 8, 3, 6, 4)))
        collect(ret)
        return ret

    def readdir(self, path, fh):
        dirents = ['.', '..']

        if path[1:] in self.index and self.index[path[1:]].obj_type == "dir":
            dirents.extend(self.index[path[1:]].data)
            collect(dirents)
            for r in dirents:
                yield r

    def readlink(self, path):
        collect()
        pathname = os.readlink(self.full_path(path))
        if pathname.startswith("/"):
            # Path name is absolute, sanitize it.
            return os.path.relpath(pathname, self.root)
        else:
            return pathname

    def mknod(self, path, mode, dev):
        collect()
        return os.mknod(self.full_path(path), mode, dev)

    def rmdir(self, path):
        collect()
        full_path = self.full_path(path)
        return os.rmdir(full_path)

    def mkdir(self, path, mode):
        collect()
        return os.mkdir(self.full_path(path), mode)

    def statfs(self, path):
        collect()
        full_path = self.full_path(path)
        stv = os.statvfs(full_path)
        return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
            'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
            'f_frsize', 'f_namemax'))

    def unlink(self, path):
        collect()
        return os.unlink(self.full_path(path))

    def symlink(self, name, target):
        collect()
        return os.symlink(target, self.full_path(name))

    def rename(self, old, new):
        collect()
        return os.rename(self.full_path(old), self.full_path(new))

    def link(self, target, name):
        collect()
        return os.link(self.full_path(name), self.full_path(target))

    def utimens(self, path, times=None):
        collect()
        return os.utime(self.full_path(path), times)

    # File methods
    # ============

    def open(self, path, flags):
        collect()
        full_path = self.full_path(path)
        return os.open(full_path, flags)

    def create(self, path, mode, fi=None):
        collect()
        uid, gid, pid = fuse_get_context()
        full_path = self.full_path(path)
        fd = os.open(full_path, os.O_WRONLY | os.O_CREAT, mode)
        os.chown(full_path,uid,gid) #chown to context uid & gid
        return fd

    def read(self, path, length, offset, fh):
        collect()
        os.lseek(fh, offset, os.SEEK_SET)
        return os.read(fh, length)

    def write(self, path, buf, offset, fh):
        collect()
        os.lseek(fh, offset, os.SEEK_SET)
        return os.write(fh, buf)

    def truncate(self, path, length, fh=None):
        collect()
        full_path = self.full_path(path)
        with open(full_path, 'r+') as f:
            f.truncate(length)

    def flush(self, path, fh):
        collect()
        return os.fsync(fh)

    def release(self, path, fh):
        collect()
        return os.close(fh)

    def fsync(self, path, fdatasync, fh):
        collect()
        return self.flush(path, fh)


class FileSystem:
    def __init__(self, root):
        os.makedirs("fs", exist_ok=True)
        self.root = root
        self.mountpoint = "fs"
        self.process = None

    def start_fuse(self):
        self.process = FUSE(Passthrough(self.root), self.mountpoint, nothreads=True, foreground=True, nonempty=True)

    def stop_fuse(self):
        if self.process:
            os.kill(self.process.pid, signal.SIGTERM)

if __name__ == "__main__":
    fs = FileSystem("", sys.argv[1])
    fs.start_fuse()