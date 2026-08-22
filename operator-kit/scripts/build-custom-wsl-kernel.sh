#!/usr/bin/env bash
set -euo pipefail

readonly SOURCE_ROOT="/home/xhw/websitebench-wsl-kernel"
readonly SOURCE_DIR="${SOURCE_ROOT}/WSL2-Linux-Kernel-linux-msft-wsl-6.18.33.2"
readonly SOURCE_ARCHIVE="/mnt/d/codework/.websitebench-tools/wsl-kernel/source/linux-msft-wsl-6.18.33.2.tar.gz"
readonly EXPECTED_SOURCE_ARCHIVE_SHA256="21f28efed81a1c097d249917000eed9ca70e8f90bfeebc687ea9b559d5310906"
readonly BUILD_DIR="/home/xhw/websitebench-wsl-kernel/build-x32off"
readonly MODULES_DIR="/home/xhw/websitebench-wsl-kernel/modules-x32off"
readonly ARTIFACT_DIR="/mnt/d/WSL/Kernels/6.18.33.2-x32off"
readonly CONFIG_FILE="${BUILD_DIR}/config.websitebench"
readonly BASE_CONFIG_FILE="${BUILD_DIR}/config.microsoft-base"
readonly SOURCE_CONFIG_FILE="${BUILD_DIR}/config.microsoft-source"
readonly EXPECTED_RELEASE="6.18.33.2-microsoft-standard-WSL2-x32off"
readonly BUILD_JOBS="${WEBSITEBENCH_KERNEL_JOBS:-8}"
readonly BUILD_STARTED_AT_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

if [[ "$(uname -s)" != "Linux" ]] || [[ "$(uname -m)" != "x86_64" ]]; then
  echo "This build requires x86_64 Linux under WSL2." >&2
  exit 2
fi
if [[ "$(id -un)" != "xhw" ]]; then
  echo "Compile as the dedicated unprivileged xhw user." >&2
  exit 2
fi
if [[ ! -f "${SOURCE_ARCHIVE}" ]]; then
  echo "Pinned Microsoft source archive is missing: ${SOURCE_ARCHIVE}" >&2
  exit 2
fi
if [[ -e "${SOURCE_DIR}" ]] || [[ -e "${BUILD_DIR}" ]] \
  || [[ -e "${MODULES_DIR}" ]] || [[ -e "${ARTIFACT_DIR}" ]]; then
  echo "Verified source, build, modules, or artifact target already exists; refusing to reuse or overwrite." >&2
  exit 2
fi
if ! [[ "${BUILD_JOBS}" =~ ^[1-9][0-9]*$ ]] || (( BUILD_JOBS > 12 )); then
  echo "WEBSITEBENCH_KERNEL_JOBS must be an integer from 1 to 12." >&2
  exit 2
fi

actual_source_archive_sha256="$(sha256sum "${SOURCE_ARCHIVE}" | cut -d ' ' -f 1)"
if [[ "${actual_source_archive_sha256}" != "${EXPECTED_SOURCE_ARCHIVE_SHA256}" ]]; then
  echo "Pinned Microsoft source archive SHA-256 mismatch." >&2
  exit 2
fi

mkdir -p "${SOURCE_ROOT}"
tar -xzf "${SOURCE_ARCHIVE}" -C "${SOURCE_ROOT}"
if [[ ! -f "${SOURCE_DIR}/Microsoft/config-wsl" ]] \
  || [[ ! -x "${SOURCE_DIR}/scripts/config" ]] \
  || [[ ! -x "${SOURCE_DIR}/scripts/diffconfig" ]]; then
  echo "Verified Microsoft WSL kernel source has an unexpected layout." >&2
  exit 2
fi

mkdir -p "${BUILD_DIR}" "${MODULES_DIR}" "${ARTIFACT_DIR}"
cp "${SOURCE_DIR}/Microsoft/config-wsl" "${SOURCE_CONFIG_FILE}"
cp "${SOURCE_CONFIG_FILE}" "${BASE_CONFIG_FILE}"

cd "${SOURCE_DIR}"
make O="${BUILD_DIR}" KCONFIG_CONFIG="${BASE_CONFIG_FILE}" olddefconfig
cp "${BASE_CONFIG_FILE}" "${CONFIG_FILE}"
scripts/config --file "${CONFIG_FILE}" --disable X86_X32_ABI
scripts/config --file "${CONFIG_FILE}" \
  --set-str LOCALVERSION "-microsoft-standard-WSL2-x32off"
make O="${BUILD_DIR}" KCONFIG_CONFIG="${CONFIG_FILE}" olddefconfig

scripts/diffconfig "${BASE_CONFIG_FILE}" "${CONFIG_FILE}" \
  > "${BUILD_DIR}/config.diff"
cat "${BUILD_DIR}/config.diff"

grep -Fx '# CONFIG_X86_X32_ABI is not set' "${CONFIG_FILE}" >/dev/null
grep -Fx 'CONFIG_IA32_EMULATION=y' "${CONFIG_FILE}" >/dev/null
grep -Fx 'CONFIG_COMPAT=y' "${CONFIG_FILE}" >/dev/null
grep -Fx 'CONFIG_SECURITY_LANDLOCK=y' "${CONFIG_FILE}" >/dev/null
grep -Fx 'CONFIG_SECCOMP=y' "${CONFIG_FILE}" >/dev/null
grep -Fx 'CONFIG_SECCOMP_FILTER=y' "${CONFIG_FILE}" >/dev/null
grep -Fx 'CONFIG_LOCALVERSION="-microsoft-standard-WSL2-x32off"' \
  "${CONFIG_FILE}" >/dev/null

unexpected_diff="$({
  grep -Ev \
    '^ (LOCALVERSION ".*" -> "-microsoft-standard-WSL2-x32off"|X86_X32_ABI y -> n)$' \
    "${BUILD_DIR}/config.diff" || true
} | sed '/^$/d')"
if [[ -n "${unexpected_diff}" ]]; then
  echo "Unexpected semantic config differences:" >&2
  printf '%s\n' "${unexpected_diff}" >&2
  exit 2
fi
if [[ "$(wc -l < "${BUILD_DIR}/config.diff")" -ne 2 ]]; then
  echo "Expected exactly two semantic config differences." >&2
  exit 2
fi

make -j"${BUILD_JOBS}" O="${BUILD_DIR}" KCONFIG_CONFIG="${CONFIG_FILE}"
kernel_release="$(make -s O="${BUILD_DIR}" KCONFIG_CONFIG="${CONFIG_FILE}" kernelrelease)"
if [[ "${kernel_release}" != "${EXPECTED_RELEASE}" ]]; then
  echo "Unexpected kernel release: ${kernel_release}" >&2
  exit 2
fi

make O="${BUILD_DIR}" KCONFIG_CONFIG="${CONFIG_FILE}" \
  INSTALL_MOD_PATH="${MODULES_DIR}" modules_install

cp "${BUILD_DIR}/arch/x86/boot/bzImage" "${ARTIFACT_DIR}/bzImage"
cp "${CONFIG_FILE}" "${ARTIFACT_DIR}/config"
cp "${BUILD_DIR}/config.diff" "${ARTIFACT_DIR}/config.diff"
cp "${BUILD_DIR}/System.map" "${ARTIFACT_DIR}/System.map"
cp "${BUILD_DIR}/Module.symvers" "${ARTIFACT_DIR}/Module.symvers"
printf '%s\n' "${EXPECTED_RELEASE}" > "${ARTIFACT_DIR}/kernel-release.txt"

sha256sum \
  "${ARTIFACT_DIR}/bzImage" \
  "${ARTIFACT_DIR}/config" \
  "${ARTIFACT_DIR}/config.diff" \
  "${ARTIFACT_DIR}/System.map" \
  "${ARTIFACT_DIR}/Module.symvers"

kernel_sha256="$(sha256sum "${ARTIFACT_DIR}/bzImage" | cut -d ' ' -f 1)"
config_sha256="$(sha256sum "${ARTIFACT_DIR}/config" | cut -d ' ' -f 1)"
config_diff_sha256="$(sha256sum "${ARTIFACT_DIR}/config.diff" | cut -d ' ' -f 1)"
system_map_sha256="$(sha256sum "${ARTIFACT_DIR}/System.map" | cut -d ' ' -f 1)"
module_symvers_sha256="$(sha256sum "${ARTIFACT_DIR}/Module.symvers" | cut -d ' ' -f 1)"
printf '%s\n' \
  '{' \
  '  "schema_version": "websitebench.wsl-kernel-build-stage.v1",' \
  "  \"build_started_at_utc\": \"${BUILD_STARTED_AT_UTC}\"," \
  "  \"build_completed_at_utc\": \"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"," \
  '  "builder_user": "xhw",' \
  "  \"build_jobs\": ${BUILD_JOBS}," \
  "  \"source_archive_sha256\": \"${actual_source_archive_sha256}\"," \
  "  \"kernel_release\": \"${EXPECTED_RELEASE}\"," \
  "  \"kernel_sha256\": \"${kernel_sha256}\"," \
  "  \"config_sha256\": \"${config_sha256}\"," \
  "  \"config_diff_sha256\": \"${config_diff_sha256}\"," \
  "  \"system_map_sha256\": \"${system_map_sha256}\"," \
  "  \"module_symvers_sha256\": \"${module_symvers_sha256}\"" \
  '}' > "${ARTIFACT_DIR}/build-stage-receipt.json"

echo "Kernel and modules built. Run finalize-custom-wsl-kernel.ps1 before activation."
