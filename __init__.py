def classFactory(iface):
    from .plugin import GeoLichenPlugin
    return GeoLichenPlugin(iface)
