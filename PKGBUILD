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
    'python-pyqt6'
    'python-textual'
    'python-keyring'
    'python-requests'
    'kwallet'
    'nodejs'
    'ollama'
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

    # Install our application's wheel. We use --no-deps because pacman
    # is handling the dependencies listed in the 'depends' array.
    pip install --root="$pkgdir" --no-deps --prefix=/usr dist/*.whl

    # Now, use pip to install ONLY the missing dependency (ollmcp) from PyPI
    # into the same system-wide site-packages directory.
    pip install --root="$pkgdir" --prefix=/usr ollmcp

    # Install .desktop and icon, and fix the icon path
    install -Dm644 assets/mcp-central.desktop "$pkgdir/usr/share/applications/$pkgname.desktop"
    install -Dm644 assets/icon.png "$pkgdir/usr/share/pixmaps/$pkgname.png"
    sed -i "s|Icon=/usr/share/pixmaps/mcp-central.png|Icon=$pkgname|" "$pkgdir/usr/share/applications/$pkgname.desktop"
}
