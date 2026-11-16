#ifndef CORTE_NATIVE_H_
#define CORTE_NATIVE_H_
#include <flutter/binary_messenger.h>
#include <flutter/encodable_value.h>
#include <flutter/method_channel.h>
#include <memory>

class CorteNativeChannel {
 public:
  explicit CorteNativeChannel(flutter::BinaryMessenger* messenger);
 private:
  std::unique_ptr<flutter::MethodChannel<flutter::EncodableValue>> channel_;
};
#endif
