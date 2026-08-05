// 데이터 모델

class UserCreateRequest {
  final String name;
  final String? phoneNumber;
  final String? ageGroup;
  final String? gender;

  UserCreateRequest({
    required this.name,
    this.phoneNumber,
    this.ageGroup,
    this.gender,
  });

  Map<String, dynamic> toJson() => {
    'name': name,
    if (phoneNumber != null) 'phoneNumber': phoneNumber,
    if (ageGroup != null) 'ageGroup': ageGroup,
    if (gender != null) 'gender': gender,
  };
}

class UserResponse {
  final int userId;
  final String name;
  final String phoneNumber;
  final String? ageGroup;
  final String? gender;
  final String? createdAt;
  final String? updatedAt;

  UserResponse({
    required this.userId,
    required this.name,
    required this.phoneNumber,
    this.ageGroup,
    this.gender,
    this.createdAt,
    this.updatedAt,
  });

  factory UserResponse.fromJson(Map<String, dynamic> json) => UserResponse(
    userId: json['userId'],
    name: json['name'],
    phoneNumber: json['phoneNumber'],
    ageGroup: json['ageGroup'],
    gender: json['gender'],
    createdAt: json['createdAt'],
    updatedAt: json['updatedAt'],
  );
}
