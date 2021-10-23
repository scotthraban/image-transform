import os
import io
import sys
import urllib
import threading
from socketserver import ThreadingMixIn
from http.server import BaseHTTPRequestHandler, HTTPServer

from PIL import Image

import mariadb

class ImageTransformHandler(BaseHTTPRequestHandler):

    _db_host = os.getenv("DB_HOST") or "127.0.0.1"
    _db_table = os.getenv("DB_TABLE") or "photos2"
    _db_username = os.getenv("DB_USERNAME") or "photos"
    _db_password = os.getenv("DB_PASSWORD") or "photos"
    _db_poolsize = int(os.getenv("POOL_SIZE") or "10")

    _root_context = os.getenv("ROOT_CONTEXT") or "/photos/photo/"

    _lfu_cache_max_count = int(os.getenv("LFU_CACHE_MAX_COUNT") or "32")

    _pool = mariadb.ConnectionPool(
        user = _db_username,
        password = _db_password,
        host = _db_host,
        port = 3306,
        pool_size = _db_poolsize,
        pool_name="photos"
        )

    _lfu_cache = {}
    _lfu_cache_counts = {}
    
    def do_GET(self):
        if not self.path.startswith(self._root_context):
            self.send_response(404)
            self.end_headers()
            return

        parts = self.path[len(self._root_context):].split("/")
        values = {}
        for i in range(0, len(parts), 2):
            if (i + 1 >= len(parts)):
                continue
            values[parts[i]] = parts[i + 1]

        if not values.get("id"):
            self.send_response(404)
            self.end_headers()
            return

        try:
            conn = self._pool.get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT path, rotation, modified_timestamp " +
                           "FROM " + self._db_table + ".photos " +
                           "WHERE id_photo = ?",
                           (values.get("id"),))

            row = cursor.fetchone()

            # don't hold the conn while transforming the photo
            conn.close()

            if row:
                path, rotation, modified = row
                
                photo_bytes = self._get_photo(
                    path, rotation, modified, values.get("size"))

                photo_bytes.seek(0, os.SEEK_END)
                size = photo_bytes.tell()
                photo_bytes.seek(0, 0)

                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', size)
                self.end_headers()

                self.wfile.write(photo_bytes.read())
            else:
                self.send_response(404)
                self.end_headers()

        except mariadb.PoolError as e:
            print(f"Error opening connection from pool {e}")
            self.send_response(503)
            self.end_headers()
        

    def _get_photo(self, path, rotation, modified, size):

        photo_bytes = self._get_cached_photo(path, rotation, modified, size)
        if photo_bytes:
            return photo_bytes
        
        rotate = rotation * -1

        factor = None
        boxWidth = None
        boxHeight = None
        
        if size:
            factor, boxWidth, boxHeight = self._get_transforms(size)
        
        if factor or (boxWidth and boxHeight):

            image = Image.open("/mnt/photos/" + path)

            if factor:
                image = image.rotate(rotate * -1, expand=1).reduce(factor)
            elif boxWidth and boxHeight:
                rotatedWidth = image.width
                rotatedHeight = image.height
                if (rotate in (90, -90, 270)):
                    rotatedWidth = image.height
                    rotatedHeight = image.width

                ratioWidth = rotatedWidth / boxWidth
                ratioHeight = rotatedHeight / boxHeight
                ratio = max(ratioWidth, ratioHeight)

                targetWidth = rotatedWidth / ratio
                targetHeight = rotatedHeight / ratio

                image = image.rotate(rotate, expand=1).resize((int(targetWidth), int(targetHeight)))
                
            photo_bytes = io.BytesIO()
            image.save(photo_bytes, "jpeg")

            self._put_cached_photo(path, rotation, modified, size, photo_bytes)
        else:
            photo_bytes = io.BytesIO(open("/mnt/photos/" + path, "rb").read())

        return photo_bytes;


    def _get_transforms(self, size):
        return {
            "full" : (1, None, None),
            "half" : (2, None, None),
            "quarter" : (4, None, None),
            "eighth" : (8, None, None),
            "xsmall" : (None, 80, 80),
            "small" : (None, 160, 160),
            "medium" : (None, 320, 320),
            "large" : (None, 640, 480),
            "xlarge" : (None, 800, 600),
            "xxlarge" : (None, 1024, 768),
            "xxxlarge" : (None, 1280, 1024),
            "xxxxlarge" : (None, 1600, 1200),
            "tivo" : (None, 320, 320),
            "blog" : (None, 852, 852),
            "home" : (None, 990, 990)}.get(size) or (None, None, None)


    def _get_cached_photo(self, path, rotation, modified, size):
        key = self._get_cached_photo_key(path, rotation, modified, size)

        photo_bytes = self._lfu_cache.get(key)
        if photo_bytes:
            self._lfu_cache_counts[key] += 1

        return photo_bytes


    def _put_cached_photo(self, path, rotation, modified, size, photo_bytes):
        key = self._get_cached_photo_key(path, rotation, modified, size)

        self._lfu_cache[key] = photo_bytes
        self._lfu_cache_counts[key] = 1

        if len(self._lfu_cache.keys()) > self._lfu_cache_max_count:
            min_used = sys.maxsize
            min_used_key = None
            for tkey in self._lfu_cache.keys():
                if tkey != key and self._lfu_cache_counts[tkey] < min_used:
                    min_used = self._lfu_cache_counts[tkey]
                    min_used_key = tkey

            if min_used_key:
                del (self._lfu_cache[min_used_key])
                del (self._lfu_cache_counts[min_used_key])

    def _get_cached_photo_key(self, path, rotation, modified, size):
        return hash((path, rotation, modified, size))


class ThreadingHttpServer(ThreadingMixIn, HTTPServer):
    pass


if __name__ == '__main__':
    imageTransformServer = ThreadingHttpServer(('', 8080), ImageTransformHandler)
    imageTransformServer.serve_forever()
