# Maintainer: Your Name <youremail@domain.com>
pkgname=mcp-central
pkgver=1.0.0
pkgrel=1
pkgdesc="A polished GUI for managing Smithery MCP servers and chatting with Ollama."
arch=('any')
url="https://github.com/your-repo/mcp-central"
license=('MIT')
depends=(
    'python'
    'python-pyqt6'
    'python-textual'
    'python-keyring'
    'python-requests'
    'python-ollmcp'
    'gnome-keyring' # or 'kwallet'
    'nodejs' # For smithery-cli via npx
    'ollama'
)
makedepends=('python-poetry')
optdepends=(
    'konsole: For launching the TUI'
    'gnome-terminal: Alternative for launching the TUI'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")
sha256sums=('SKIP') # Replace with actual sum after downloading

package() {
    cd "$srcdir/$pkgname-$pkgver"

    # Build the package using poetry
    poetry build --format wheel

    # Install the package using pip
    pip install --root="$pkgdir" --no-deps --no-user dist/*.whl

    # Install .desktop and icon
    install -Dm644 assets/mcp-central.desktop "$pkgdir/usr/share/applications/mcp-central.desktop"
    install -Dm644 assets/icon.png "$pkgdir/usr/share/pixmaps/mcp-central.png"
}
