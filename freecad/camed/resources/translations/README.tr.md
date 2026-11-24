# CAMed çevirileri

[English](README.md)

CAMed, İngilizce metinleri `FreeCAD.Qt.translate("CAMed", source)` ile çevirir
ve bu dizini `FreeCADGui.addLanguagePath` ile FreeCAD'e tanıtır. FreeCAD,
uygulama diline uygun kataloğu seçer. Türkçe çeviri `CAMed_tr.ts` ve derlenmiş
`CAMed_tr.qm` dosyalarında bulunur.

Uygulama dilini değiştirdikten sonra FreeCAD'i yeniden başlatın. Açık pencereler
ve belgede önceden kaydedilmiş etiketler yeniden adlandırılmaz. FreeCAD'in
yerleşik pencereleri kendi çevirilerini kullanır.

## Çeviriyi güncelleme

`tr(...)` içinde İngilizce sabit metinler kullanın. Adlandırılmış alanları
çeviriden sonra biçimlendirin. Örneğin `tr("Line {line}").format(line=number)`.
G-code, tanımlayıcılar, dosya adları, kullanıcı metinleri ve ayrıştırıcının
eşleştirme kalıpları çeviri çağrılarının dışında kalır.

Eklentinin kök dizininde kataloğu güncelleyin.

```text
python tools/update_translations.py
```

TS dosyasını Qt Linguist veya bir XML düzenleyicisinde açın. Yer tutucuları,
biçim belirteçlerini ve satır sonlarını koruyun. Ardından Qt'nin `lrelease`
aracıyla kataloğu derleyin.

```text
lrelease freecad/camed/resources/translations/CAMed_tr.ts -qm freecad/camed/resources/translations/CAMed_tr.qm
```

`lrelease` FreeCAD geliştirme ortamından geliyorsa o ortamın Qt kitaplıklarını
PATH'e ekleyin. TS ve QM dosyalarını birlikte dağıtın.

## Yeni dil ekleme

`CAMed_<locale>.ts` dosyasında `sourcelanguage="en"`, hedef `language` kodu ve
`CAMed` bağlamı tanımlayın. Güncelleme aracı eksik mesajları tamamlanmamış olarak
ekler. Çevirileri tamamlayıp QM dosyasını derleyin.

Katalog testleri kapsama, yer tutuculara ve satır sonlarına bakar. Ekran dışı
Qt testleri de derlenmiş kataloğu yükleyip arayüz metinlerini ve uyarıları
doğrular.
