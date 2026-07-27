# Community apps

Standalone BUSY Bar apps prepared for the community gallery. Each app accepts
`--host`, defaults to the physical USB address, and also runs in the local
emulator on port 8088.

## Busy Newsroom

```bash
python3 community-apps/busy-newsroom/app.py --host 127.0.0.1:8088
python3 community-apps/busy-newsroom/app.py --host 10.0.4.20 \
  --feed https://feeds.npr.org/1001/rss.xml --source NPR
```

Newsroom is standard-library-only and supports RSS 2.0 and Atom feeds.
