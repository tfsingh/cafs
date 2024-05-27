import sys

from file_system import FileSystem
from indexer import Indexer 

directory = sys.argv[1]
indexer = Indexer(directory)
indexer.index()

fs = FileSystem(directory)
fs.start_fuse()
