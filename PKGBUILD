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

    # Install our application's wheel. Pip will handle installing all Python
    # dependencies declared in the wheel, including the bundled mcp-client-for-ollama.
    pip install --root="$pkgdir" --prefix=/usr dist/*.whl

    # Install .desktop and icon, and fix the icon path
    install -Dm644 assets/mcp-central.desktop "$pkgdir/usr/share/applications/$pkgname.desktop"
    install -Dm644 assets/icon.png "$pkgdir/usr/share/pixmaps/$pkgname.png"
    sed -i "s|Icon=/usr/share/pixmaps/mcp-central.png|Icon=$pkgname|" "$pkgdir/usr/share/applications/$pkgname.desktop"
}
