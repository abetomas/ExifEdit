# UTILS  README  
  
ExifEdit was initially written as my complementary tool to DAM (**D**igital**A**sset**M**anagement) software to facilitate organization of my scanned photos.   Photo albums are created by filtering keywords stored in exif metadata.  
* I have used Digikam and Adobe Bridge as my DAM to manage photos.  
* For keywords, Digikam extensively uses -TagsList, Adobe Bridge uses -Subject, Adobe Lightroom uses -HierarchicalSubject.  
* To maintain interoperability across DAMs, keyword tags are copied and synchronized across the various tags used.  In my workflow, -HierarchicalSubject is considered the master keyword dictionary.  Its keyword hierarchy is also considered in Digikam.  Note:  In Digikam, if both -TagsList and -HierarchicalSubject contain values, -TagsList takes precedence.  
  
This folder contains scripts and notes used in this project.  

| Name | Purpost |
| ----------------------------- | ------------------------------------------------------------------------------------------------- |
| automator.info.plist | Apply these changes in Automator info.plist to enable ‘Open With… Exif-Edit’ in Finder |
| automator.script | Automator script for /Applications folder |
| exifedit.py | GUI front-end for exiftool.  See repo homepage |
| exif-hierarchical_to_tags.zsh | One-time migration shell script to copy content of -HierarchicalSubject to -TagsList and -Subject |
| exif-sync-tags.zsh | Periodic shell script to sync -TagsList contents with -Subject and -HierarchicalSubject |
| fix_exif_digitizedtime.py | Fix files with missing DateTimeDigitized |
| stamp-mtime.py | Rename files using mtime, update DateTimeDigitizedß |
  
