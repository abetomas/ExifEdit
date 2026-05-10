# ExifEdit   
  
**Yet another editor for EXIF/IPTC/XMP metadata in photos.**  
This is a GUI front-end for the excellent *exiftool* of Phil Harvey.   It was initially developed as a complementary and quick exif editor for scanned photos managed in DAM software.    
## Features :  
* Update individual files  
* Batch apply exif changes to selected files  
* Copy tags from one file to other files  
* GPS input using format 'Latitude, Longitude', e.g. 45.221553, -81.531583  
* For scanned images stamp datetimes on -DateTimeOriginal -DateTimeDigitized -CreateDate  
* Add/delete Tag Contents  
* Export exif to CSV file  
## Requires :  
* exiftool         (brew install exiftool)  
* PyQt6           (pip install PyQt6)  
* Pillow            (pip install Pillow)  
* pillow-heif    (pip install pillow-heif)   # optional – HEIC preview  
## Usage :   
>     $  python3 exifedit.py [file]  
>
>* Profiles are stored in ~/.exifeditor_profiles.json  
>* exiftool must be on PATH  
## License :  
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.  
  
Requirements drafted by	:	A.Tomas  
Python Code Author		: 	[claude.ai](http://claude.ai)  
## Acknowledgments :  
* exiftool by Phil Harvey  
* Contributors of Python Libraries  
## Platform  
| Platform               | Status         |
| ---------------------- | -------------- |
| macOS (Apple Silicon)  | ✅ Tested       |
| macOS (Intel)          | 🔶 Should work  |
| Windows                | ⚠️ Untested     |
| Linux                  | ⚠️ Untested     |
* Developed using Python 3.14.4  
* Developed and tested on macOS/Apple Silicon (Tahoe)   
* Cross-platform code is in place but Windows and Linux are untested  
* Contributions and bug reports welcome!  
  
  
