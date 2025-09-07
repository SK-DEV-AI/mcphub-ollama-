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

    # Install the main application wheel without its dependencies.
    pip install --root="$pkgdir" --no-deps --prefix=/usr dist/*.whl

    # Install all Python dependencies directly with pip into the package.
    # This is the most robust method to avoid system vs. PyPI naming conflicts.
    pip install --root="$pkgdir" --prefix=/usr \
        mcp \
        ollama \
        "prompt-toolkit>=3.0.0" \
        rich \
        typer \
        httpx \
        "keyring>=25.0.0"

    # Install .desktop and icon, and fix the icon path
    install -Dm644 assets/mcp-central.desktop "$pkgdir/usr/share/applications/$pkgname.desktop"
    install -Dm644 assets/icon.png "$pkgdir/usr/share/pixmaps/$pkgname.png"
    sed -i "s|Icon=/usr/share/pixmaps/mcp-central.png|Icon=$pkgname|" "$pkgdir/usr/share/applications/$pkgname.desktop"
}
