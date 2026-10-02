# Rebuild from the pinned base with fresh distro packages, without publishing a tag.
IMAGE_AUDIT_IMAGE ?= immich-memories:audit
IMAGE_AUDIT_FILE ?= docker/Dockerfile
IMAGE_AUDIT_DEVICE ?= cpu
IMAGE_AUDIT_OUTPUT ?= image-audit

.PHONY: image-audit-build image-audit
image-audit-build:
	docker build --pull --no-cache -f "$(IMAGE_AUDIT_FILE)" -t "$(IMAGE_AUDIT_IMAGE)" \
		--build-arg APP_VERSION=0+g$$(git rev-parse --short HEAD) \
		--build-arg INSTALL_EXTRAS=all --build-arg DEVICE="$(IMAGE_AUDIT_DEVICE)" .

image-audit:
	python3 scripts/image_inventory.py --image "$(IMAGE_AUDIT_IMAGE)" --output "$(IMAGE_AUDIT_OUTPUT)"
