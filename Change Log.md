# Change Log  
  
### v-1.0.0	2026-04-30   
* Initial version  
### v-1.0.1	2026-05-06   
* Accept files/folder in argv (Finder "Open With" support)  
* Right-click context menu on thumbnails (Open With, Reveal in Finder)  
* App display name + icon improvements  
### v-1.0.2	2026-05-06   
* Fix Dock balloon tooltip showing 'Python' instead of 'Exif Edit' (NSProcessInfo.setProcessName_ + setproctitle fallback)  
### v-1.0.3	2026-05-06   
* Fix exiftool PATH resolution when launched as .app   
* (_find_exiftool() + EXIFTOOL constant; py2app alias + full build safe)  
### v-1.0.4	2026-05-06   
* Cross-platform support (Windows / Linux) for GitHub release   
* (open_with_default, reveal_in_filemanager, open_with_app helpers)  
### v-1.1.0	2026-05-08   
* DAM keyword tag support  
* Rename XMP:Subject → XMP-dc:Subject  
* Rename XMP:HierarchicalSubject → XMP-lr:HierarchicalSubject  
* Add XMP-digiKam:TagsList and IPTC:Keywords (keywords widget)  
* Keywords saved as multi-value exiftool args (one per keyword)  
* Dynamic "Open With" context menu via NSWorkspace (macOS)  
* parse_exif now stores XMP-ns:Tag keys alongside XMP:Tag  
### v-1.1.1	2026-05-09   
* Per-tag placeholder text for TagsList (slash "/") and HierarchicalSubject (pipe "|")  
* Remove IPTC:Keywords input widget (confusing due to contextual display)  
* Normalise keyword display after save: add space after comma separators to match exiftool/Raw EXIF output format  
### v-1.1.2	2026-05-20   
* Fix GPS save: write only XMP:GPSLatitude / XMP:GPSLongitude as decimal