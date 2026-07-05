# Docker Configuration Directory

This directory is mounted into the container at `/app/config/`.

Place optional runtime configuration files here before starting Docker containers.
Configuration changes persist across container restarts without rebuilding the image.

## Volume mount

```yaml
volumes:
  - ./config:/app/config
```

## Optional files

Add YAML or JSON configuration files as needed for your deployment.
Keep secrets out of version control — only commit `*.example` templates.
