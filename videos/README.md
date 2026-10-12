# Physical design video slots

The Timing card on the portfolio page includes `setup-hold-timing.mp4`, a 44-second animated whiteboard lesson. The other two cards let you preview a video chosen from your device; these browser previews are temporary and do not upload or save the selected file.

To publish your own clip in a slot:

1. Add an optimized `.mp4` or `.webm` file to this folder.
2. In `index.html`, find the matching `.video-preview` element and set its source. For example:

   ```html
   <video class="video-preview" controls playsinline preload="metadata" aria-label="Floorplanning and congestion video preview" poster="assets/setup-hold-poster.jpg">
     <source src="videos/floorplanning.mp4" type="video/mp4">
   </video>
   ```

3. Remove `hidden` from the matching video element and add `hidden` to its `.video-empty` and `.video-empty-label` placeholders so the published clip appears immediately.
4. Keep the “Preview another clip” picker if you want to try a temporary local file in that slot.

The lesson source storyboard can be regenerated with `python3 videos/make_setup_hold_video.py` on macOS with Python Pillow and Swift/AVFoundation available.
