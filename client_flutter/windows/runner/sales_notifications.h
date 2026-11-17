#ifndef CORTE_SALES_NOTIFICATIONS_H_
#define CORTE_SALES_NOTIFICATIONS_H_
#include <windows.h>
#include <flutter/method_channel.h>
#include <flutter/encodable_value.h>
#include <memory>
#include <optional>
#include <set>
#include <string>

class SalesNotifications {
 public:
  SalesNotifications(HWND window, flutter::BinaryMessenger* messenger);
  ~SalesNotifications();
  std::optional<LRESULT> Handle(UINT message, WPARAM wparam, LPARAM lparam);
 private:
  HWND window_;
  std::unique_ptr<flutter::MethodChannel<flutter::EncodableValue>> channel_;
  bool enabled_ = false, tray_ = false, busy_ = false, quitting_ = false;
  std::string scope_, launch_route_;
  std::set<std::string> seen_;
  bool AddTray();
  void RemoveTray();
  void Open(bool sales);
  void LoadSeen();
  bool SaveSeen();
};
#endif
