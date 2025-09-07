# Maintainer: Your Name <youremail@domain.com>
pkgname=mcp-central
pkgver=1.0.0
pkgrel=2
pkgdesc="A polished GUI for managing Smithery MCP servers and chatting with Ollama."
arch=('any')
url="https://github.com/SK-DEV-AI/mcphub-ollama-.git"
license=('MIT')
depends=(
    'python'
    'kwallet'
    'nodejs'
    'ollama'
    'python-prompt-toolkit'
    'python-rich'
    'python-typer'
    'python-httpx'
    'python-keyring'
)
makedepends=(
    'git'
    'python-poetry'
    'python-pip'
)
optdepends=(
    'konsole: For launching the TUI'
)
source=("$pkgname::git+$url")
sha256sums=('SKIP') # It's recommended to generate and use a real checksum

build() {
    cd "$srcdir/$pkgname"
    poetry build --format wheel
}

package() {
    cd "$srcdir/$pkgname"

    # Install the main application wheel without its dependencies, as pacman is handling them.
    pip install --root="$pkgdir" --no-deps --prefix=/usr dist/*.whl

    # Install PyPI-only dependencies that are not in the official Arch repos.
    pip install --root="$pkgdir" --prefix=/usr mcp ollama

    # Install .desktop and icon, and fix the icon path
    install -Dm644 assets/mcp-central.desktop "$pkgdir/usr/share/applications/$pkgname.desktop"
    install -Dm644 assets/icon.png "$pkgdir/usr/share/pixmaps/$pkgname.png"
    sed -i "s|Icon=/usr/share/pixmaps/mcp-central.png|Icon=$pkgname|" "$pkgdir/usr/share/applications/$pkgname.desktop"
}
