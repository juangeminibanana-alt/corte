#include "sales_notifications.h"
#include "resource.h"
#include <flutter/standard_method_codec.h>
#include <shellapi.h>
#include <shlobj.h>
#include <filesystem>
#include <fstream>
#include <regex>
#include <vector>

namespace {
using V = flutter::EncodableValue;
using M = flutter::EncodableMap;
constexpr UINT kTray = WM_APP + 81;
constexpr UINT_PTR kBalloonTimer = 22813;
std::string Text(const M& args, const char* key) {
  const auto at = args.find(V(key));
  if (at == args.end()) return "";
  const auto value = std::get_if<std::string>(&at->second);
  return value ? *value : "";
}
std::wstring Wide(const std::string& text) {
  const auto size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0);
  if (size <= 0) return L"";
  std::wstring value(size, L'\0');
  MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), value.data(), size);
  return value;
}
std::filesystem::path SeenPath(const std::string& scope) {
  PWSTR raw = nullptr;
  if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &raw))) return {};
  std::filesystem::path root(raw); CoTaskMemFree(raw);
  return root / L"CreatorHub" / L"flutter_client" / L"sales" / (Wide(scope) + L".seen");
}
}

SalesNotifications::SalesNotifications(HWND window, flutter::BinaryMessenger* messenger) : window_(window) {
  channel_ = std::make_unique<flutter::MethodChannel<V>>(messenger, "corte/sales", &flutter::StandardMethodCodec::GetInstance());
  channel_->SetMethodCallHandler([this](const flutter::MethodCall<V>& call, std::unique_ptr<flutter::MethodResult<V>> result) {
    try {
      const M empty;
      auto args = call.arguments() ? std::get_if<M>(call.arguments()) : nullptr;
      if (!args) args = &empty;
      const auto method = call.method_name();
      if (method == "notificationPermission" || method == "requestNotificationPermission") {
        result->Success(V("concedido")); return;
      }
      if (method == "notificationLaunchRoute") {
        result->Success(launch_route_.empty() ? V() : V(launch_route_));
        launch_route_.clear(); return;
      }
      if (method == "configureSales") {
        const auto at = args->find(V("enabled"));
        const auto value = at == args->end() ? nullptr : std::get_if<bool>(&at->second);
        const auto scope = Text(*args, "cache_scope");
        const bool requested = value && *value && std::regex_match(scope, std::regex("[a-f0-9]{64}"));
        if (scope_ != scope) { seen_.clear(); scope_ = requested ? scope : ""; if (requested) LoadSeen(); }
        enabled_ = requested;
        if (enabled_) enabled_ = AddTray(); else RemoveTray();
        result->Success(V(enabled_)); return;
      }
      if (method == "showSaleNotification") {
        const auto id = Text(*args, "id");
        if (!enabled_ || scope_ != Text(*args, "cache_scope") || Text(*args, "ruta") != "#/ventas"
            || !std::regex_match(id, std::regex("[0-9]{1,20}"))) { result->Success(V(false)); return; }
        if (seen_.count(id)) { result->Success(V(true)); return; }
        if (busy_ || !AddTray()) { result->Success(V(false)); return; }
        const auto title = Text(*args, "titulo"), body = Text(*args, "texto");
        if (title.empty() || title.size() > 500 || body.empty() || body.size() > 2000) { result->Success(V(false)); return; }
        NOTIFYICONDATAW data{}; data.cbSize = sizeof(data); data.hWnd = window_; data.uID = 1;
        data.uFlags = NIF_INFO; data.dwInfoFlags = NIIF_INFO | NIIF_RESPECT_QUIET_TIME;
        wcsncpy_s(data.szInfoTitle, Wide(title).c_str(), _TRUNCATE);
        wcsncpy_s(data.szInfo, Wide(body).c_str(), _TRUNCATE);
        const bool shown = Shell_NotifyIconW(NIM_MODIFY, &data) != FALSE;
        if (shown) {
          busy_ = true; SetTimer(window_, kBalloonTimer, 20000, nullptr);
          seen_.insert(id);
          // Keep a bounded receipt log for retries/restarts without storing sale text.
          while (seen_.size() > 1000) seen_.erase(seen_.begin());
          SaveSeen();
        }
        result->Success(V(shown)); return;
      }
      result->NotImplemented();
    } catch (...) { result->Error("notifications_unavailable", "No se pudo actualizar el aviso de venta."); }
  });
}

SalesNotifications::~SalesNotifications() { channel_->SetMethodCallHandler(nullptr); RemoveTray(); }

bool SalesNotifications::AddTray() {
  if (tray_) return true;
  NOTIFYICONDATAW data{}; data.cbSize = sizeof(data); data.hWnd = window_; data.uID = 1;
  data.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP | NIF_SHOWTIP;
  data.uCallbackMessage = kTray;
  data.hIcon = LoadIconW(GetModuleHandle(nullptr), MAKEINTRESOURCE(IDI_APP_ICON));
  wcscpy_s(data.szTip, L"CUTGC \u00b7 Avisos de ventas activos");
  tray_ = Shell_NotifyIconW(NIM_ADD, &data) != FALSE;
  if (tray_) { data.uVersion = NOTIFYICON_VERSION_4; Shell_NotifyIconW(NIM_SETVERSION, &data); }
  return tray_;
}

void SalesNotifications::RemoveTray() {
  KillTimer(window_, kBalloonTimer); busy_ = false;
  if (!tray_) return;
  NOTIFYICONDATAW data{}; data.cbSize = sizeof(data); data.hWnd = window_; data.uID = 1;
  Shell_NotifyIconW(NIM_DELETE, &data); tray_ = false;
}

void SalesNotifications::Open(bool sales) {
  ShowWindow(window_, IsIconic(window_) ? SW_RESTORE : SW_SHOW);
  SetForegroundWindow(window_);
  if (sales) { launch_route_ = "#/ventas"; channel_->InvokeMethod("saleNotificationOpened", nullptr); }
}

std::optional<LRESULT> SalesNotifications::Handle(UINT message, WPARAM wparam, LPARAM lparam) {
  static const UINT taskbar = RegisterWindowMessageW(L"TaskbarCreated");
  if (message == taskbar && enabled_) { tray_ = false; AddTray(); return 0; }
  if (message == WM_CLOSE && enabled_ && tray_ && !quitting_) { ShowWindow(window_, SW_HIDE); return 0; }
  if (message == WM_TIMER && wparam == kBalloonTimer) { busy_ = false; KillTimer(window_, kBalloonTimer); return 0; }
  if (message != kTray) return std::nullopt;
  const UINT event = LOWORD(lparam);
  if (event == NIN_BALLOONTIMEOUT || event == NIN_BALLOONHIDE || event == NIN_BALLOONUSERCLICK) {
    busy_ = false; KillTimer(window_, kBalloonTimer);
    if (event == NIN_BALLOONUSERCLICK) Open(true);
  } else if (event == NIN_SELECT || event == NIN_KEYSELECT || event == WM_LBUTTONDBLCLK) {
    Open(false);
  } else if (event == WM_CONTEXTMENU) {
    POINT point{}; GetCursorPos(&point);
    HMENU menu = CreatePopupMenu();
    if (menu) {
      AppendMenuW(menu, MF_STRING, 1, L"Abrir CUTGC");
      AppendMenuW(menu, MF_STRING, 2, L"Salir de CUTGC");
      SetForegroundWindow(window_);
      const auto action = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, point.x, point.y, 0, window_, nullptr);
      DestroyMenu(menu);
      if (action == 1) Open(false);
      if (action == 2) { quitting_ = true; DestroyWindow(window_); }
    }
  }
  return 0;
}

void SalesNotifications::LoadSeen() {
  try {
    const auto path = SeenPath(scope_);
    if (path.empty() || !std::filesystem::is_regular_file(path) || std::filesystem::file_size(path) > 24000) return;
    std::ifstream input(path); std::string id;
    while (seen_.size() < 1000 && std::getline(input, id)) if (std::regex_match(id, std::regex("[0-9]{1,20}"))) seen_.insert(id);
  } catch (...) { /* Online device acknowledgments remain authoritative. */ }
}

bool SalesNotifications::SaveSeen() {
  try {
    const auto path = SeenPath(scope_); if (path.empty()) return false;
    std::filesystem::create_directories(path.parent_path());
    auto temp = path; temp += L".new";
    { std::ofstream output(temp, std::ios::trunc); for (const auto& id : seen_) output << id << '\n'; output.flush(); if (!output) return false; }
    return MoveFileExW(temp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != FALSE;
  } catch (...) { return false; }
}
