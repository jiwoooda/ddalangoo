// 데이터 모델

class UserCreateRequest {
  final String name;
  final String? phoneNumber;
  final String? ageGroup;

  UserCreateRequest({required this.name, this.phoneNumber, this.ageGroup});

  Map<String, dynamic> toJson() => {
    'name': name,
    if (phoneNumber != null) 'phoneNumber': phoneNumber,
    if (ageGroup != null) 'ageGroup': ageGroup,
  };
}

class UserResponse {
  final int userId;
  final String name;
  final String phoneNumber;
  final String? ageGroup;
  final String? createdAt;

  UserResponse({
    required this.userId,
    required this.name,
    required this.phoneNumber,
    this.ageGroup,
    this.createdAt,
  });

  factory UserResponse.fromJson(Map<String, dynamic> json) => UserResponse(
    userId: json['userId'],
    name: json['name'],
    phoneNumber: json['phoneNumber'],
    ageGroup: json['ageGroup'],
    createdAt: json['createdAt'],
  );
}
