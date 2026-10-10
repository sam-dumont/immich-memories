# A real Basic release download and Compose validation, without starting an app.
# make demo-compose-setup extracts the final frame; no shell paths enter the image.
Output "/tmp/immich-compose-setup.mp4"

Require curl
Require docker
Require docker-compose

Set Shell "bash"
Set FontSize 22
Set Width 1600
Set Height 520
Set Theme "GitHub Dark"
Set Padding 24
Set Framerate 10

Hide
Type ".venv/bin/python scripts/demo-compose-setup.py"
Enter
Wait+Screen@60s /❯ curl/
Show
Wait+Screen@120s /ghcr.io\/sam-dumont\/immich-memories:1.0.0-rc.9/
Sleep 500ms
Hide
