import CoreWLAN
import Foundation

guard let interface = CWWiFiClient.shared().interface() else {
    fputs("No Wi-Fi interface\n", stderr)
    exit(1)
}

do {
    let networks = try interface.scanForNetworks(withSSID: nil)
        .sorted { $0.rssiValue > $1.rssiValue }
    for network in networks {
        let ssid = network.ssid ?? "<hidden>"
        let bssid = network.bssid ?? ""
        let channel = network.wlanChannel?.channelNumber ?? 0
        let band = network.wlanChannel?.channelBand == .band5GHz ? "5 GHz" :
            (network.wlanChannel?.channelBand == .band2GHz ? "2.4 GHz" : "other")
        print("\(network.rssiValue)\t\(network.noiseMeasurement)\t\(channel)\t\(band)\t\(bssid)\t\(ssid)")
    }
} catch {
    fputs("Wi-Fi scan failed: \(error)\n", stderr)
    exit(2)
}
