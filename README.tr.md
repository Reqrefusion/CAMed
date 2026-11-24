# CAMed

[English](README.md)

CAMed, FreeCAD için bir G-code editörüdür. Takım yolu önizleme, stok ve takım
ayarları, delme çevrimleri ve simülasyon sunar.

## Özellikler

- G-code’u sözdizimi renklendirmesiyle düzenleyin, metin arayıp değiştirin ve program bölümleri arasında gezinin.
- Kod değiştikçe takım yolunu önizleyin. Kutu veya silindir stok tanımlayın ve takımları T numarasına göre eşleyin.
- Formdan delme çevrimi ekleyin ve üretilen G-code’u önizleyin.
- FreeCAD’de talaş kaldırmayı simüle edin. İlgili simülasyon adımına gitmek için bir G-code satırı seçin.

## Kurulum

1. FreeCAD’de **Araçlar → Eklenti Yöneticisi**’ni açın.
2. Ayarlarda **Özel depolar** bölümüne [CAMed GitHub deposunu](https://github.com/Reqrefusion/CAMed)
   ekleyin ve dal olarak `main` girin.
3. Listeden **CAMed**’i seçip **Yükle**’ye basın. FreeCAD’i yeniden başlatıp
   **CAMed** çalışma tezgâhını seçin.

## Kullanım

1. **Ctrl+O** ile bir G-code dosyası açın veya **Yeni CAMed projesi** ile boş
   bir program oluşturun.
2. **Stok…** aracından stok şeklini ve ölçülerini ayarlayın. Gerekiyorsa
   **İşin takımları…** bölümünden takımları ve T numaralarını tanımlayın.
3. **Simülasyon** görünümünü açıp oynatma düğmesine basın. Simülasyonda bir
   noktaya gitmek için editörde ilgili satırı seçin.
4. G-code’u **Ctrl+S** ile kaydedin. Stok ve takımları da birlikte saklamak
   için **FreeCAD projesini kaydet…** komutunu kullanın.

Arayüz FreeCAD’in dil ayarını izler ve İngilizce ile Türkçeyi destekler.

[Bakım notları](MAINTENANCE.tr.md) · [Lisans](LICENSE)
