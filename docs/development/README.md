# Developer documentation

Docs for working on the TV Time Capsule codebase. For running the app as an operator, see [Usage docs](../usage/README.md).

## Contents

1. [Development setup](setup.md) — Poetry, running locally  
2. [Architecture](architecture.md) — runtime flow, ports/adapters, Pi vs desktop  
3. [Module map](modules.md) — package layout and responsibilities  
3a. [Native weather & cached defaults](../usage/native-cached-defaults.md) — product defaults + live opt-in (operator + architecture)  
4. [Packaging & release](packaging.md) — Poetry, pipx, wheels, assets  
5. [Scripts reference](scripts-reference.md) — `scripts/` and `install-pi.sh`  
6. [Remote mount testing](remote-mount-testing.md) — local Docker harness for Samba / SFTP / FTP  
7. [WSL2 on Windows](wsl2.md) — develop on Windows via Linux  
8. [Improvement plan](improvement-plan.md) — phased roadmap and retros  
9. [Pi features & offline YouTube](pi-features-offline-youtube-plan.md) — feature gates, adaptive Weather, forever yt-dlp cache, crop parity, test plans
