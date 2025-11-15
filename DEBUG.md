# Debugging Guide

## Quick Debug Commands

### View Flask logs in real-time
```bash
docker compose logs gui -f
```

### View only recent logs
```bash
docker compose logs gui --tail 50
```

### Check Let's Encrypt logs
```bash
# Windows
Get-Content cert_data\logs\letsencrypt.log -Tail 50

# Linux/Mac
tail -50 cert_data/logs/letsencrypt.log
```

### Check running containers
```bash
docker ps
docker ps --filter name=nginx
docker ps --filter name=certbot
```

### Test nginx is serving challenge files
```bash
# Check if challenge directory exists in nginx
docker exec nginx ls -la /var/www/certbot/.well-known/acme-challenge/

# Test HTTP access (from host)
curl http://localhost/.well-known/acme-challenge/test
```

### Check port bindings
```bash
# Windows
netstat -ano | findstr :80
netstat -ano | findstr :443

# Linux/Mac
netstat -tulpn | grep :80
netstat -tulpn | grep :443
```

## Common Issues

### Port 80 already in use
- **Symptom**: `Bind for 0.0.0.0:80 failed: port is already allocated`
- **Solution**: Stop other services using port 80, or check what's using it with `netstat`

### Certificate challenge fails with 404
- **Symptom**: `Invalid response from https://domain/.well-known/acme-challenge/...: 404`
- **Possible causes**:
  1. Domain doesn't point to this server's public IP
  2. Port 80/443 not forwarded/accessible from internet
  3. Firewall blocking inbound connections
  4. Nginx not serving challenge files correctly

### Container name conflicts
- **Symptom**: `Conflict. The container name "/nginx" is already in use`
- **Solution**: The code now automatically removes existing containers, but you can manually remove with:
  ```bash
  docker rm -f nginx
  docker rm -f certbot
  ```

## Debug Mode

Flask is running in debug mode, which provides:
- Detailed error messages with stack traces
- Auto-reload on code changes (since code is mounted as volume)
- Debugger PIN (shown in logs) for interactive debugging

## Testing Certificate Generation

1. Ensure domain points to your server's public IP
2. Ensure ports 80 and 443 are forwarded and accessible
3. Start the stack: `docker compose up -d`
4. Wait for Flask to start (check logs)
5. Submit certificate request via web UI at `http://localhost:8070` or via curl:
   ```bash
   curl -X POST http://localhost:8070 -d "domain=yourdomain.com&email=your@email.com"
   ```
6. Monitor logs: `docker compose logs gui -f`

