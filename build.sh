docker buildx build \
  --platform linux/arm64/v8,linux/amd64 \
  --push \
  --tag docker-registry.hraban.com/image-transform:latest \
  --tag docker-registry.hraban.com/image-transform:2.1 \
  .