#include "corte_native.h"
#include <flutter/standard_method_codec.h>
#include <windows.h>
#include <shlobj.h>
#include <wincrypt.h>
#include <bcrypt.h>
#include <winrt/Windows.Data.Json.h>
#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

// System SQLite is read-only here. No original database is created or migrated.
extern "C" {
struct sqlite3;
struct sqlite3_stmt;
__declspec(dllimport) int sqlite3_open_v2(const char*, sqlite3**, int, const char*);
__declspec(dllimport) int sqlite3_close(sqlite3*);
__declspec(dllimport) int sqlite3_busy_timeout(sqlite3*, int);
__declspec(dllimport) int sqlite3_prepare_v2(sqlite3*, const char*, int, sqlite3_stmt**, const char**);
__declspec(dllimport) int sqlite3_step(sqlite3_stmt*);
__declspec(dllimport) int sqlite3_finalize(sqlite3_stmt*);
__declspec(dllimport) const unsigned char* sqlite3_column_text(sqlite3_stmt*, int);
__declspec(dllimport) const void* sqlite3_column_blob(sqlite3_stmt*, int);
__declspec(dllimport) int sqlite3_column_bytes(sqlite3_stmt*, int);
}

namespace {
using Value = flutter::EncodableValue;
using Map = flutter::EncodableMap;
using Bytes = std::vector<uint8_t>;
using winrt::Windows::Data::Json::JsonObject;
using winrt::Windows::Data::Json::JsonValue;
namespace fs = std::filesystem;
std::string Utf8Path(const fs::path& path) {
  const auto value = path.u8string();
  return std::string(reinterpret_cast<const char*>(value.data()), value.size());
}
constexpr size_t kMax = 20 * 1024 * 1024;
const std::map<std::string, std::wstring> kKeys = {
 {"corte.nube.dispositivo.v1", L"device"},
 {"corte.nube.autorizacion.v1", L"pending"},
 {"corte.nube.propietario.v1", L"owner"}};

void Require(bool ok) { if (!ok) throw std::runtime_error("native storage unavailable"); }
fs::path LegacyRoot() {
  PWSTR path = nullptr;
  Require(SUCCEEDED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &path)));
  fs::path root(path); CoTaskMemFree(path); return root / L"CreatorHub";
}
fs::path DataRoot() {
  auto root = LegacyRoot() / L"flutter_client";
  fs::create_directories(root); return root;
}
std::optional<Bytes> ReadFile(const fs::path& path, size_t limit = kMax) {
  if (!fs::is_regular_file(path)) return std::nullopt;
  const auto size = fs::file_size(path); Require(size <= limit);
  Bytes bytes(static_cast<size_t>(size)); std::ifstream input(path, std::ios::binary);
  Require(static_cast<bool>(input));
  input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
  Require(static_cast<bool>(input) || size == 0); return bytes;
}
void WriteAtomic(const fs::path& path, const Bytes& bytes) {
  fs::create_directories(path.parent_path()); auto temp = path; temp += L".new";
  HANDLE file = CreateFileW(temp.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
  Require(file != INVALID_HANDLE_VALUE); DWORD written = 0;
  const bool ok = WriteFile(file, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr)
      && written == bytes.size() && FlushFileBuffers(file);
  CloseHandle(file); Require(ok);
  Require(MoveFileExW(temp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != FALSE);
}
Bytes Protect(const Bytes& input, const std::string& entropy, bool decrypt) {
  DATA_BLOB in{static_cast<DWORD>(input.size()), const_cast<BYTE*>(input.data())};
  DATA_BLOB salt{static_cast<DWORD>(entropy.size()), reinterpret_cast<BYTE*>(const_cast<char*>(entropy.data()))};
  DATA_BLOB out{};
  BOOL ok = decrypt ? CryptUnprotectData(&in, nullptr, &salt, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &out)
      : CryptProtectData(&in, L"Corte", &salt, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &out);
  Require(ok != FALSE); Bytes result(out.pbData, out.pbData + out.cbData);
  SecureZeroMemory(out.pbData, out.cbData); LocalFree(out.pbData); return result;
}
std::string Text(const Bytes& bytes) { return std::string(bytes.begin(), bytes.end()); }
Bytes Encode(const std::string& text) { return Bytes(text.begin(), text.end()); }
std::string Json(const JsonObject& object) { return winrt::to_string(object.Stringify()); }
std::string Hash(const std::string& text) {
  BCRYPT_ALG_HANDLE algorithm = nullptr; unsigned char digest[32]{};
  Require(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0);
  const auto status = BCryptHash(algorithm, nullptr, 0, reinterpret_cast<PUCHAR>(const_cast<char*>(text.data())),
      static_cast<ULONG>(text.size()), digest, sizeof(digest));
  BCryptCloseAlgorithmProvider(algorithm, 0); Require(status >= 0);
  constexpr char hex[] = "0123456789abcdef"; std::string result;
  for (auto byte : digest) { result += hex[byte >> 4]; result += hex[byte & 15]; }
  return result;
}
struct Query {
  sqlite3_stmt* statement = nullptr;
  Query(sqlite3* db, const char* sql) { Require(sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == 0); }
  ~Query() { if (statement) sqlite3_finalize(statement); }
  bool Next() { const int status = sqlite3_step(statement); Require(status == 100 || status == 101); return status == 100; }
  std::string String(int column) {
    auto text = sqlite3_column_text(statement, column); const int size = sqlite3_column_bytes(statement, column);
    Require(size >= 0 && static_cast<size_t>(size) <= kMax);
    return text ? std::string(reinterpret_cast<const char*>(text), static_cast<size_t>(size)) : "";
  }
};
struct Database {
  sqlite3* db = nullptr;
  Database() {
    const auto path = LegacyRoot() / L"datos" / L"cliente_nube.sqlite";
    Require(fs::is_regular_file(path));
    if (sqlite3_open_v2(Utf8Path(path).c_str(), &db, 1, nullptr) != 0) {
      if (db) sqlite3_close(db); db = nullptr; Require(false);
    }
    sqlite3_busy_timeout(db, 2000);
    Query only(db, "PRAGMA query_only=ON"); only.Next();
  }
  ~Database() { if (db) sqlite3_close(db); }
  std::string Owner() {
    Query q(db, "SELECT v FROM meta WHERE k='owner_uid'"); return q.Next() ? q.String(0) : "";
  }
};
std::optional<Bytes> LegacyRead(const std::string& name) {
  Require(name == "snapshot" || name == "meta" || name == "outbox" || name == "archive_snapshot" || name == "archive_outbox");
  if (name.rfind("archive_", 0) == 0 || !fs::is_regular_file(LegacyRoot() / L"datos" / L"cliente_nube.sqlite")) return std::nullopt;
  Database data;
  if (name == "snapshot") {
    Query q(data.db, "SELECT body FROM cache WHERE k='/api/snapshot' AND status=200");
    if (!q.Next()) return std::nullopt;
    const int size = sqlite3_column_bytes(q.statement, 0); Require(size > 0 && static_cast<size_t>(size) <= kMax);
    auto bytes = static_cast<const uint8_t*>(sqlite3_column_blob(q.statement, 0)); Require(bytes != nullptr);
    return Bytes(bytes, bytes + size);
  }
  if (name == "meta") {
    JsonObject object; object.SetNamedValue(L"platform", JsonValue::CreateStringValue(L"windows"));
    const auto owner = data.Owner();
    object.SetNamedValue(L"owner_scope", owner.empty() ? JsonValue::CreateNullValue() : JsonValue::CreateStringValue(winrt::to_hstring(Hash("corte-owner:" + owner))));
    object.SetNamedValue(L"cache_scope", JsonValue::CreateNullValue());
    object.SetNamedValue(L"creator_binding_verified", JsonValue::CreateBooleanValue(false));
    Query q(data.db, "SELECT v FROM meta WHERE k='snapshot_revision'");
    object.SetNamedValue(L"snapshot_revision", q.Next() ? JsonValue::CreateStringValue(winrt::to_hstring(q.String(0))) : JsonValue::CreateNullValue());
    return Encode(Json(object));
  }
  Query q(data.db, "SELECT op,estado,resultado FROM cola ORDER BY rowid"); std::string output; size_t count = 0;
  while (q.Next()) {
    Require(++count <= 5000); JsonObject row;
    row.SetNamedValue(L"op", JsonValue::Parse(winrt::to_hstring(q.String(0))));
    row.SetNamedValue(L"estado", JsonValue::CreateStringValue(winrt::to_hstring(q.String(1))));
    const auto result = q.String(2);
    row.SetNamedValue(L"resultado", result.empty() ? JsonValue::CreateNullValue() : JsonValue::Parse(winrt::to_hstring(result)));
    output += Json(row) + "\n"; Require(output.size() <= kMax);
  }
  return Encode(output);
}
std::optional<std::string> OldDevice() {
  std::optional<JsonObject> best; double generation = -1;
  for (const auto& suffix : {L"", L".nuevo"}) {
    try {
      auto path = LegacyRoot() / L"secretos" / (std::wstring(L"dispositivo_nube.dpapi") + suffix);
      auto raw = ReadFile(path, 1024 * 1024); if (!raw) continue;
      const auto envelope = JsonObject::Parse(winrt::to_hstring(Text(*raw)));
      Require(envelope.GetNamedNumber(L"v") == 1); const double gen = envelope.GetNamedNumber(L"generacion");
      const auto encoded = winrt::to_string(envelope.GetNamedString(L"blob")); DWORD size = 0;
      Require(CryptStringToBinaryA(encoded.data(), static_cast<DWORD>(encoded.size()), CRYPT_STRING_BASE64 | CRYPT_STRING_STRICT, nullptr, &size, nullptr, nullptr) != FALSE);
      Bytes blob(size); Require(CryptStringToBinaryA(encoded.data(), static_cast<DWORD>(encoded.size()), CRYPT_STRING_BASE64 | CRYPT_STRING_STRICT, blob.data(), &size, nullptr, nullptr) != FALSE);
      const auto plain = Protect(blob, "Corte/dispositivo-nube/v1", true);
      const auto device = JsonObject::Parse(winrt::to_hstring(Text(plain)));
      if (gen > generation) { best = device; generation = gen; }
    } catch (...) { /* Keep every original file unchanged, including unreadable candidates. */ }
  }
  if (!best) return std::nullopt;
  JsonObject result;
  result.SetNamedValue(L"token", JsonValue::CreateStringValue(best->GetNamedString(L"native_token")));
  result.SetNamedValue(L"device_id", JsonValue::CreateStringValue(best->GetNamedString(L"device_id")));
  result.SetNamedValue(L"expires_at", JsonValue::CreateNumberValue(best->GetNamedNumber(L"expires_at")));
  // Auth validates the imported token with Corte before presenting any account or cache.
  return Json(result);
}
std::string Argument(const Map& args, const char* name) {
  auto found = args.find(Value(name)); Require(found != args.end());
  auto value = std::get_if<std::string>(&found->second); Require(value != nullptr); return *value;
}
}  // namespace

CorteNativeChannel::CorteNativeChannel(flutter::BinaryMessenger* messenger) {
  channel_ = std::make_unique<flutter::MethodChannel<Value>>(messenger, "corte/native", &flutter::StandardMethodCodec::GetInstance());
  channel_->SetMethodCallHandler([](const flutter::MethodCall<Value>& call, std::unique_ptr<flutter::MethodResult<Value>> result) {
    try {
      const Map empty; const auto* args = call.arguments() ? std::get_if<Map>(call.arguments()) : nullptr;
      if (!args) args = &empty;
      const auto& method = call.method_name();
      if (method == "dataRoot") { result->Success(Value(Utf8Path(DataRoot()))); return; }
      if (method == "legacyInfo") {
        const bool exists = fs::is_regular_file(LegacyRoot() / L"datos" / L"cliente_nube.sqlite");
        Map info{{Value("platform"), Value("windows")}, {Value("dataRoot"), Value(Utf8Path(DataRoot()))},
          {Value("legacyRoot"), Value(Utf8Path(LegacyRoot()))}, {Value("hasSnapshot"), Value(exists)},
          {Value("hasMeta"), Value(exists)}, {Value("hasOutbox"), Value(exists)},
          {Value("hasArchiveSnapshot"), Value(false)}, {Value("hasArchiveOutbox"), Value(false)}};
        result->Success(Value(info)); return;
      }
      if (method == "legacyRead") {
        auto bytes = LegacyRead(Argument(*args, "name")); result->Success(bytes ? Value(*bytes) : Value()); return;
      }
      if (method != "secureRead" && method != "secureWrite" && method != "secureDelete") { result->NotImplemented(); return; }
      const auto key = Argument(*args, "key"); const auto found = kKeys.find(key); Require(found != kKeys.end());
      const auto path = DataRoot() / L"secure" / (found->second + L".dpapi");
      auto deleted = path; deleted += L".deleted";
      const auto entropy = "Corte/flutter/native/v1/" + key;
      if (method == "secureRead") {
        if (fs::exists(deleted)) { result->Success(); return; }
        auto bytes = ReadFile(path, 128 * 1024);
        if (bytes) { result->Success(Value(Text(Protect(*bytes, entropy, true)))); return; }
        auto legacy = key == "corte.nube.dispositivo.v1" ? OldDevice() : std::nullopt;
        result->Success(legacy ? Value(*legacy) : Value()); return;
      }
      if (method == "secureWrite") {
        const auto value = Argument(*args, "value"); Require(value.size() <= 65536);
        WriteAtomic(path, Protect(Encode(value), entropy, false));
        if (fs::exists(deleted)) Require(DeleteFileW(deleted.c_str()) != FALSE);
      } else {
        // A tombstone prevents a signed-out device from resurrecting the preserved legacy credential.
        WriteAtomic(deleted, Bytes{1});
        if (fs::exists(path)) Require(DeleteFileW(path.c_str()) != FALSE);
      }
      result->Success();
    } catch (...) {
      result->Error("native_storage_unavailable", "No pudimos acceder al almacenamiento privado. Los datos anteriores se conservan.");
    }
  });
}
