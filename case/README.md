# ESP32 case

A 3D-printable case for the ESP32-S3-DevKitC-1 N16R8, adapted for mounting
behind the rowing machine.

It is a remix of
[ESP32-S3 DevKitC-1 Case by peaberry](https://www.thingiverse.com/thing:7284377),
licensed CC BY-SA 4.0. This folder is shared under the same licence –
unlike the rest of this repository, which is MIT. See [LICENSE](LICENSE).

![Plan view and longitudinal section](preview.png)

| File | Part |
|---|---|
| `esp32case_mod_bottom.stl` | Bottom, ~29 g PLA, 112 × 57 × 16 mm |
| `esp32case_mod_top.stl` | Lid, ~7 g PLA |

## Changes to the original

**Bottom**
- Side hole for the external antenna closed.
- Cable plinth in front of the two USB-C ports, 32 mm long, its top just
  below the plug housings, with a zip-tie tunnel running across it.
- Zip-tie ears on both long sides, flush with the underside.
- Repaired: the original STL had one back-to-back duplicate triangle (a
  zero-thickness fin), so it was not a closed solid.

**Lid**
- RST/BOOT button holes closed.
- **WR** engraved over the port that goes to the WaterRower monitor and a
  lightning bolt over the power port, 0.6 mm deep.

## Printing

- **Bottom:** floor on the bed, like the original. Plinth and ears sit
  flush with the underside, the tie tunnel bridges 5.6 mm. No supports.
- **Lid:** top face down on the bed, like the original (its lip points
  up). The engraving then forms in the first layers and comes out crisp.

## Zip ties

- Up to ~5 mm wide: tunnel 5.6 × 1.8 mm, ear slots 5.5 × 2.6 mm.
- **Strain relief:** one tie through the tunnel and over both cables holds
  them on the plinth past the plug housings, so a pull on a cable does not
  reach the ESP's sockets.
- **Mounting:** a tie through each ear around a strut or tube. One tie
  through both ears crosses the lid, which is fine.

With RST and BOOT covered, flashing over USB with BOOT held – only needed
if an OTA update ever leaves the ESP unbootable – means opening the case.
