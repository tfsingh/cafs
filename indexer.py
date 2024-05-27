import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from constants import INDEX_STORAGE, FILE_STORAGE 

class IndexObj:
    def __init__(self, path, obj_type, data=None, stat=None):
        # in the case of file or link, this is a hashed path. otherwise it's an actual path (dirlink resolves to dir actual path)
        self.path = path
        # dir, dirlink, file, link
        self.obj_type = obj_type
        # stores dir contents for readdir
        self.data = data
        # stat struct computed from hashed rootfs
        self.stat = stat

class Indexer:
    def __init__(self, source_path):
        os.makedirs(INDEX_STORAGE, exist_ok=True)
        os.makedirs(FILE_STORAGE, exist_ok=True)

        self.rootfs_path_to_index_obj = {}
        self.seen = set()
        self.source_path = source_path
        self.target_path = f"target-files-{source_path}"
        self.index_path = os.path.join(INDEX_STORAGE, source_path)

    def index(self):
        os.makedirs(self.target_path, exist_ok=True)

        self.generate_index(self.source_path, self.target_path)
        self.handle_links(self.source_path, self.target_path)
        self.produce_stat()

        for key, obj in self.rootfs_path_to_index_obj.items():
            obj.path = re.sub(r'target-files-[^/]+', f'{FILE_STORAGE}', obj.path)

        with open(self.index_path + ".json", 'w') as index_file:
            json.dump(self.rootfs_path_to_index_obj, index_file, default=vars, indent=4)        

        shutil.copytree(self.target_path, FILE_STORAGE, dirs_exist_ok=True)

        shutil.rmtree(self.target_path, ignore_errors=True)

    def generate_index(self, directory, target_directory):
        items = os.listdir(directory)
        self.rootfs_path_to_index_obj[self.clean_path(directory)] = IndexObj(self.clean_path(directory), "dir", data=items)

        for item in items:
            source_item_path = os.path.join(directory, item)
            if source_item_path in self.seen or os.path.islink(source_item_path):
                continue

            self.seen.add(source_item_path)

            if os.path.isdir(source_item_path):
                new_target_directory = os.path.join(target_directory, item)
                if not os.path.exists(new_target_directory):
                    os.makedirs(new_target_directory)

                self.generate_index(source_item_path, new_target_directory)
            elif os.path.isfile(source_item_path):
                try:
                    with open(source_item_path, 'rb') as f:
                        file_contents = f.read()
                        file_hash = hashlib.md5(file_contents).hexdigest()
                except Exception as e:
                    print(f"Error reading file {source_item_path}: {e}")
                    continue

                hashed_file_path = os.path.join(target_directory, file_hash)
                if not os.path.exists(hashed_file_path):
                    shutil.copy2(source_item_path, hashed_file_path)

                self.rootfs_path_to_index_obj[self.clean_path(source_item_path)] = IndexObj(hashed_file_path, "file")

    def handle_links(self, directory, target_directory):
        for item in os.listdir(directory):
            source_item_path = os.path.join(directory, item)
            target_item_path = os.path.join(target_directory, item)

            real_path = os.path.realpath(source_item_path)
            real_path = self.clean_path(real_path)

            temp = source_item_path
            links = set()
            while os.path.islink(temp):
                if temp in links:
                    break
                links.add(temp)
                temp = os.readlink(temp)
            
            if real_path in self.rootfs_path_to_index_obj:
                for link in links:
                    self.rootfs_path_to_index_obj[self.clean_path(link)] = IndexObj(self.rootfs_path_to_index_obj[real_path].path, "link")

            if os.path.isdir(source_item_path):
                if os.path.islink(source_item_path):
                    real_path = os.path.join(self.target_path, real_path)
                    self.rootfs_path_to_index_obj[target_item_path.split(f"{self.target_path}/")[1]] = IndexObj(real_path, "dirlink")
                else:
                    self.handle_links(source_item_path, target_item_path)

    def produce_stat(self):
        self.rootfs_path_to_index_obj[''] = IndexObj('', "dir", data=os.listdir(self.target_path))
        del self.rootfs_path_to_index_obj[self.source_path]
        for file_path, index_obj in self.rootfs_path_to_index_obj.items():
            try:
                stat_path = index_obj.path
                if index_obj.obj_type == "dir":
                    stat_path = os.path.join(self.target_path, stat_path)
                index_obj.stat = os.lstat(stat_path)
            except Exception as e:
                print(f"Error producing stat for {file_path}: {e}")
                continue

    def clean_path(self, link):
        if link.startswith("/"):
            link = link[1:]

        link = link.split(f"{self.source_path}/")

        return link[1] if len(link) > 1 else link[0]
