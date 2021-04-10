#!/usr/bin/env python3
import os
import shutil
import datetime
from PIL import Image
import argparse
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("-d", "--directory", type=str,
	help="image directory", required=False)
args = vars(parser.parse_args())
img_directory = None

class PhotoOrganizer:
    DATETIME_EXIF_INFO_ID = 36867
    extensions = ['jpg', 'jpeg', 'png', 'nef', 'mov']
    # run exiftool for getting datetime rather then PIL
    exiftool_extensions = ['mov', 'nef']

    def folder_path_from_photo_date(self, file):
        date = self.photo_shooting_date(file)
        return date.strftime('%Y') + '/' + date.strftime('%Y-%m-%d')

    def photo_shooting_date(self, file):
        date = None
        # if os.path.isfile(img_directory + '/' + filename) and any(filename.lower().endswith('.' + ext.lower()) for ext in self.extensions)
        if (any(file.lower().endswith('.' + ext.lower()) for ext in self.exiftool_extensions)):
            EXIFTOOL_DATE_TAG_VIDEOS = "Create Date"
            cmd = "exiftool '%s'" % file
            output = subprocess.check_output(cmd, shell=True)
            lines = output.decode("ascii").split("\n")
            for l in lines:
                if EXIFTOOL_DATE_TAG_VIDEOS in l:
                        datetime_str = l.split(" : ")[1]
                        date = datetime.datetime.strptime(datetime_str,
                                                         "%Y:%m:%d %H:%M:%S")
                        # exiftool prints two lines of Create Date tag, getting the first accurance only
                        break
            if date is None:
                date = datetime.datetime.fromtimestamp(os.path.getmtime(file))
            return date
        else:
            photo = Image.open(file)
            if hasattr(photo, '_getexif'):
                info = photo._getexif()
                if info:
                    if self.DATETIME_EXIF_INFO_ID in info:
                        date = info[self.DATETIME_EXIF_INFO_ID]
                        date = datetime.datetime.strptime(date, '%Y:%m:%d %H:%M:%S')
            if date is None:
                date = datetime.datetime.fromtimestamp(os.path.getmtime(file))
            return date

    def move_photo(self, file):
        new_folder = self.folder_path_from_photo_date(img_directory + '/' + file)
        if not os.path.exists(new_folder):
            os.makedirs(new_folder)
        shutil.move(img_directory + '/' + file, new_folder + '/' + file)

    def organize(self):
        photos = [
            filename for filename in os.listdir(img_directory)
                if os.path.isfile(img_directory + '/' + filename) and any(filename.lower().endswith('.' + ext.lower()) for ext in self.extensions)
        ]
        for filename in photos:
            self.move_photo(filename)


if args.get("directory", False):
    img_directory = args.get("directory")
else:
    img_directory = '.'

PO = PhotoOrganizer()
PO.organize()
