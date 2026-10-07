# Worker app container: shares its gluetun sibling's network and runs the
# scripts you send. Includes bash + common tools so real .sh scripts work
# (busybox sh alone chokes on bashisms like C-style for loops).
FROM alpine:3.22
RUN apk add --no-cache bash curl coreutils grep sed jq ca-certificates tzdata
CMD ["sleep", "infinity"]
